"""Block q step Q1: FR39 stale documents, with backdated rows on agila_test (never Eo's data) and
a fixed `now`, so every boundary is exact."""

import ast
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agila import stale
from agila.export import local_date
from agila.stale import Stale, StaleDocument, find_stale, format_stale

MANILA = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=MANILA)
NOTHING = "Nothing stale this week"


def _doc(conn, title, saved_at, *, asked=None, status="active", visibility="anywhere"):
    """One backdated document row (no chunks are needed for /stale)."""
    return conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
        " content_hash, saved_at, last_asked_at, status, visibility)"
        " VALUES ((SELECT id FROM spaces LIMIT 1), %s, 'text', %s, %s, 'h', %s, %s, %s, %s)"
        " RETURNING id",
        (title, title, f"text:{title}", saved_at, asked, status, visibility),
    ).fetchone()[0]


def _days(n):
    return NOW - timedelta(days=n)


def _months_ago(n):
    """`n` calendar months before NOW (same day and time)."""
    month = NOW.month - n
    year = NOW.year + (month - 1) // 12
    return NOW.replace(year=year, month=(month - 1) % 12 + 1)


def _found(conn, **options):
    result = find_stale(conn, now=NOW, **options)
    return [(d.title, d.reason) for d in result.documents]


# --- FR39: the rule (database, backdated rows) ---


@pytest.mark.db
def test_never_asked_and_older_than_30_days_is_stale(conn):
    _doc(conn, "31 days, never asked", _days(31))
    assert _found(conn) == [("31 days, never asked", "never asked")]


@pytest.mark.db
def test_never_asked_but_29_days_old_is_not_stale(conn):
    _doc(conn, "29 days", _days(29))
    assert _found(conn) == []


@pytest.mark.db
def test_exactly_30_days_old_is_not_stale_yet(conn):
    _doc(conn, "exactly 30 days", _days(30))  # the rule is "older than"
    assert _found(conn) == []


@pytest.mark.db
def test_asked_recently_and_31_days_old_is_not_stale(conn):
    _doc(conn, "31 days, asked", _days(31), asked=_days(5))
    assert _found(conn) == []


@pytest.mark.db
def test_older_than_12_months_is_stale_even_when_asked_yesterday(conn):
    _doc(conn, "13 months, asked", _months_ago(13), asked=_days(1))
    assert _found(conn) == [("13 months, asked", "older than 12 months")]


@pytest.mark.db
def test_older_than_12_months_and_never_asked_gives_the_age_reason(conn):
    _doc(conn, "2 years, never asked", _months_ago(24))
    assert _found(conn) == [("2 years, never asked", "older than 12 months")]


@pytest.mark.db
def test_exactly_12_months_old_and_asked_is_not_stale(conn):
    _doc(conn, "12 months, asked", _months_ago(12), asked=_days(1))
    assert _found(conn) == []


@pytest.mark.db
@pytest.mark.parametrize("status", ["archived", "superseded"])
def test_archived_and_superseded_documents_are_never_stale(conn, status):
    _doc(conn, f"2 years, {status}", _months_ago(24), status=status)
    assert _found(conn) == []


@pytest.mark.db
def test_a_backdated_private_document_is_omitted_by_default_and_listed_with_include_private(conn):
    _doc(conn, "13 months, private", _months_ago(13), visibility="laptop_only")
    _doc(conn, "13 months, public", _months_ago(13))
    assert _found(conn) == [("13 months, public", "older than 12 months")]
    result = find_stale(conn, now=NOW)
    assert (result.total, [d.title for d in result.documents]) == (1, ["13 months, public"])
    with_private = find_stale(conn, now=NOW, include_private=True)
    assert [d.title for d in with_private.documents] == ["13 months, private", "13 months, public"]
    assert with_private.total == 2


@pytest.mark.db
def test_nothing_stale_gives_the_fr30_sentence(conn):
    _doc(conn, "fresh", _days(2))
    result = find_stale(conn, now=NOW)
    assert (result.documents, result.total) == ([], 0)
    assert format_stale(result) == NOTHING


@pytest.mark.db
def test_oldest_first_and_ties_by_id(conn):
    tie_a = _doc(conn, "tie a", _days(60))
    oldest = _doc(conn, "oldest", _months_ago(20))
    tie_b = _doc(conn, "tie b", _days(60))
    ids = [d.document_id for d in find_stale(conn, now=NOW).documents]
    assert ids == [oldest, tie_a, tie_b]


@pytest.mark.db
def test_a_limit_cuts_the_rows_but_total_counts_them_all(conn):
    for n in range(3):
        _doc(conn, f"old {n}", _days(40 + n))
    result = find_stale(conn, now=NOW, limit=2)
    assert ([d.title for d in result.documents], result.total) == (["old 2", "old 1"], 3)
    assert format_stale(result).splitlines()[-1] == "Showing 2 of 3. Use the CLI stale for all."


@pytest.mark.db
def test_a_document_carries_its_dates_and_type(conn):
    asked = _months_ago(14)
    document = _doc(conn, "old and asked once", _months_ago(15), asked=asked)
    (found,) = find_stale(conn, now=NOW).documents
    assert (found.document_id, found.source_type) == (document, "text")
    assert found.saved_at == _months_ago(15)
    assert found.last_asked_at == asked
    assert found.saved_at.tzinfo is not None


@pytest.mark.db
def test_without_now_the_database_clock_is_used(conn):
    _doc(conn, "really old", datetime(2020, 1, 1, tzinfo=UTC))
    _doc(conn, "just saved", datetime.now(UTC))
    assert [d.title for d in find_stale(conn).documents] == ["really old"]


@pytest.mark.db
def test_finding_stale_documents_changes_nothing(conn):
    _doc(conn, "old", _days(45))
    sql = "SELECT id, saved_at, last_asked_at, status FROM documents ORDER BY id"
    before = conn.execute(sql).fetchall()
    find_stale(conn, now=NOW, include_private=True)
    assert conn.execute(sql).fetchall() == before
    assert conn.execute("SELECT count(*) FROM query_log").fetchone() == (0,)


# --- the text (plain, no database) ---

SAVED = datetime(2025, 9, 1, 9, 0, tzinfo=UTC)


def _stale(*docs, total=None):
    return Stale(list(docs), len(docs) if total is None else total)


def _one(n=4, title="An old page", reason="never asked", source_type="web"):
    return StaleDocument(n, title, source_type, SAVED, None, reason)


def test_format_stale_lists_each_document_with_its_reason():
    text = format_stale(_stale(_one(4), _one(9, "A note", "older than 12 months", "text")))
    assert text.splitlines() == [
        "Stale documents: 2.",
        f"4  {local_date(SAVED)}  web  An old page  (never asked)",
        f"9  {local_date(SAVED)}  text  A note  (older than 12 months)",
    ]


def test_format_stale_with_nothing_is_the_fr30_sentence():
    assert format_stale(_stale()) == NOTHING  # no full stop (FR30)


def test_format_stale_adds_the_overflow_line_when_cut():
    text = format_stale(_stale(_one(1), _one(2), total=25))
    lines = text.splitlines()
    assert lines[0] == "Stale documents: 25."
    assert lines[-1] == "Showing 2 of 25. Use the CLI stale for all."
    assert len(lines) == 4


def test_the_stale_sentences_are_at_most_25_words():
    sentences = [NOTHING, "Stale documents: 120.", "Showing 20 of 120. Use the CLI stale for all."]
    assert all(len(s.split()) <= 25 for s in sentences)  # NFR7


def test_the_limit_used_by_the_api_is_20():
    assert stale.LIMIT == 20


def test_stale_imports_no_model_http_or_vault_writer():
    source = Path(stale.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not imported & {"agila.llm", "httpx", "agila.web", "agila.questions"}
