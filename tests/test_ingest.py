import contextlib
import io
from datetime import UTC, datetime

import numpy as np
import pytest

from agila import ask, db, ingest, library, llm, netcheck, retrieval
from agila.chunking import CACHE_DIR


def test_missing_markdown_file_prints_one_sentence(tmp_path, capsys):
    code = ingest.main(["markdown", str(tmp_path / "nope.md")])
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("File not found:")
    assert "Traceback" not in out


def test_missing_text_file_prints_one_sentence(tmp_path, capsys):
    code = ingest.main(["text", "--title", "T", "--label", "L", "--file", str(tmp_path / "x.txt")])
    assert code == 1
    assert capsys.readouterr().out.startswith("File not found:")


def test_missing_variable_is_named_without_a_traceback(tmp_path, monkeypatch, capsys):
    note = tmp_path / "n.md"
    note.write_text("# Hi\nSome text.", encoding="utf-8")
    for name in db.ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    code = ingest.main(["markdown", str(note)])
    out = capsys.readouterr().out
    assert code == 1
    assert "POSTGRES_HOST" in out
    assert "Traceback" not in out


def test_text_command_needs_title_and_label():
    with pytest.raises(SystemExit):
        ingest.main(["text", "--title", "T"])


# --- ingest url (block f part 2): no database and no network are used in these tests ---


def _no_database():
    return contextlib.nullcontext(None)  # save_url refuses before it would touch the connection


def test_url_command_refuses_a_typo_link_with_one_sentence(capsys):
    code = ingest.main(["url", "htp://example.test/a"], connect=_no_database)
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("Only http and https links")
    assert "Traceback" not in out


def test_url_command_refuses_localhost_with_one_sentence(capsys):
    code = ingest.main(["url", "http://localhost:8000/"], connect=_no_database)
    out = capsys.readouterr().out
    assert code == 1
    assert "private, local or reserved" in out
    assert "Traceback" not in out


def test_url_command_refuses_the_cloud_metadata_address(monkeypatch, capsys):
    async def numeric_only(host, port):  # what the system gives for a numeric address
        return [host]

    monkeypatch.setattr(netcheck, "system_resolver", numeric_only)
    code = ingest.main(["url", "http://169.254.169.254/latest/meta-data"], connect=_no_database)
    out = capsys.readouterr().out
    assert code == 1
    assert "private, local or reserved" in out
    assert "Traceback" not in out


def test_url_command_prints_the_stored_title(monkeypatch, capsys):
    calls = []

    def fake_save(conn, url, title=None, replace=False):
        calls.append((url, title, replace))
        return library.Saved(1, 4, "The page title")

    monkeypatch.setattr(ingest, "save_url", fake_save)
    code = ingest.main(["url", "https://example.test/a", "--title", "Mine"], connect=_no_database)
    assert code == 0
    assert calls == [("https://example.test/a", "Mine", False)]
    assert capsys.readouterr().out == "Saved The page title: 4 chunks\n"


# --- block g: list, archive, unarchive, delete and --replace ---

needs_model = pytest.mark.skipif(
    not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed"
)


class FakeEmbedder:
    def passage_embed(self, texts):
        return (np.full(384, i, dtype=np.float32) for i in range(len(texts)))


def _test_database(empty_db):
    return lambda: db.connect(dbname=empty_db)  # the throwaway agila_test, never agila


@pytest.mark.db
@needs_model
def test_list_command_prints_title_date_status_and_visibility(conn, empty_db, capsys):
    kept = library.save_text(conn, "Kept note", "k", "Some kept text.", FakeEmbedder())
    library.save_text(conn, "Active note", "a", "Some active text.", FakeEmbedder())
    library.archive(conn, kept.document_id)
    conn.commit()
    assert ingest.main(["list"], connect=_test_database(empty_db)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    for line, title, status in zip(
        lines, ("Active note", "Kept note"), ("active", "archived"), strict=True
    ):
        assert (title in line, today in line, status in line, "anywhere" in line) == (
            True, True, True, True
        )


def test_list_command_on_an_empty_library_prints_one_sentence(monkeypatch, capsys):
    monkeypatch.setattr(ingest, "list_documents", lambda conn: [])
    assert ingest.main(["list"], connect=_no_database) == 0
    assert capsys.readouterr().out == "No documents saved yet.\n"


@pytest.mark.db
@needs_model
def test_delete_without_yes_deletes_nothing(conn, empty_db, capsys):
    saved = library.save_text(conn, "My note", "n", "Some text.", FakeEmbedder())
    conn.commit()
    assert ingest.main(["delete", str(saved.document_id)], connect=_test_database(empty_db)) == 0
    out = capsys.readouterr().out
    assert out.startswith(f'Would delete document {saved.document_id} "My note" (text, saved ')
    assert "1 chunks). Nothing deleted. Run again with --yes" in out
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


@pytest.mark.db
@needs_model
def test_delete_with_yes_prints_the_title_and_chunk_count(conn, empty_db, capsys):
    saved = library.save_text(conn, "My note", "n", "Some text.", FakeEmbedder())
    conn.commit()
    code = ingest.main(
        ["delete", str(saved.document_id), "--yes"], connect=_test_database(empty_db)
    )
    assert code == 0
    assert capsys.readouterr().out == (
        f'Deleted document {saved.document_id} "My note" and its 1 chunks.\n'
    )
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


@pytest.mark.db
def test_delete_of_an_unknown_id_prints_one_sentence(conn, empty_db, capsys):
    for argv in (["delete", "999999"], ["delete", "999999", "--yes"], ["archive", "999999"]):
        assert ingest.main(argv, connect=_test_database(empty_db)) == 1
        assert capsys.readouterr().out == "No document with id 999999.\n"


@pytest.mark.parametrize("bad", ["abc", "0", "-3", str(2**63)])
def test_a_document_id_must_be_a_whole_number(bad):
    with pytest.raises(SystemExit):
        ingest.main(["delete", bad], connect=_no_database)


@pytest.mark.parametrize(
    ("argv", "name"),
    [
        (["text", "--title", "T", "--label", "L", "--replace"], "save_text"),
        (["markdown", "NOTE", "--replace"], "save_markdown"),
        (["url", "https://example.test/a", "--replace"], "save_url"),
    ],
)
def test_replace_flag_reaches_the_library(argv, name, tmp_path, monkeypatch, capsys):
    note = tmp_path / "n.md"
    note.write_text("# Hi\nSome text.", encoding="utf-8")
    argv = [str(note) if a == "NOTE" else a for a in argv]
    monkeypatch.setattr("sys.stdin", io.StringIO("Some text."))
    calls = []

    def fake(*args, replace=False, **kwargs):
        calls.append(replace)
        return library.Saved(7, 2, "T", "replaced", (3,))

    monkeypatch.setattr(ingest, name, fake)
    assert ingest.main(argv, connect=_no_database) == 0
    assert calls == [True]
    assert capsys.readouterr().out.endswith(". It replaces document 3, now superseded.\n")


def test_a_label_warning_is_printed_on_its_own_line(monkeypatch, capsys):
    warning = 'Warning: a different note labelled L is already saved as document 1 "Old"'
    monkeypatch.setattr(
        ingest, "save_text", lambda *a, **k: library.Saved(2, 1, "T", warning=warning)
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("Some text."))
    assert ingest.main(["text", "--title", "T", "--label", "L"], connect=_no_database) == 0
    assert capsys.readouterr().out == f"Saved T: 1 chunks\n{warning}\n"


# --- block h: ingest search (search faked: no database, no model) ---


def _result(passages, best=None, threshold=retrieval.PROVISIONAL_MIN_SIMILARITY):
    best = passages[0].similarity if passages and best is None else best
    return retrieval.SearchResult(passages, best, threshold)


def _passage(similarity, heading=None, text="Short passage text."):
    return retrieval.Passage(
        11, text, heading, None, "llm-wiki", "https://example.test/wiki",
        datetime(2026, 10, 21, 9, 0, tzinfo=UTC), similarity,
    )


def test_search_command_prints_passages_with_score_title_and_source(monkeypatch, capsys):
    calls = []

    def fake_search(conn, question, *, min_similarity):
        calls.append((question, min_similarity))
        return _result([_passage(0.786, heading="Setup", text="word " * 100), _passage(0.717)])

    monkeypatch.setattr(ingest, "search", fake_search)
    assert ingest.main(["search", "How do I build a wiki?"], connect=_no_database) == 0
    lines = capsys.readouterr().out.splitlines()
    assert calls == [("How do I build a wiki?", 0.70)]
    saved = datetime(2026, 10, 21, 9, 0, tzinfo=UTC).astimezone().strftime("%Y-%m-%d")
    assert lines[0] == f"1. 0.79  llm-wiki  (https://example.test/wiki, saved {saved})"
    assert lines[1] == "   Section: Setup"
    assert lines[2].endswith("...") and len(lines[2]) == 3 + 300 + 3
    assert lines[3].startswith("2. 0.72  llm-wiki")
    assert lines[4] == "   Short passage text."


def test_search_command_says_nothing_close_enough_with_the_score(monkeypatch, capsys):
    monkeypatch.setattr(ingest, "search", lambda conn, q, *, min_similarity: _result([], 0.402))
    assert ingest.main(["search", "Who won the 2022 FIFA World Cup?"], connect=_no_database) == 0
    assert capsys.readouterr().out == (
        "Nothing close enough: the best similarity was 0.40,"
        " below the provisional threshold 0.70.\n"
    )


def test_min_similarity_is_for_that_search_only(monkeypatch, capsys):
    calls = []

    def fake_search(conn, question, *, min_similarity):
        calls.append(min_similarity)
        return _result([], 0.65, min_similarity)

    monkeypatch.setattr(ingest, "search", fake_search)
    assert ingest.main(["search", "q", "--min-similarity", "0.8"], connect=_no_database) == 0
    assert calls == [0.8]
    assert capsys.readouterr().out == (
        "Nothing close enough: the best similarity was 0.65, below the threshold 0.80.\n"
    )
    assert retrieval.PROVISIONAL_MIN_SIMILARITY == 0.70  # the constant never changes


def test_search_command_on_an_empty_library(monkeypatch, capsys):
    monkeypatch.setattr(ingest, "search", lambda conn, q, *, min_similarity: _result([], None))
    assert ingest.main(["search", "q"], connect=_no_database) == 0
    assert capsys.readouterr().out == "No documents saved yet.\n"


@pytest.mark.parametrize("bad", ["abc", "1.5", "-2", "nan"])
def test_a_bad_min_similarity_is_refused(bad):
    with pytest.raises(SystemExit):
        ingest.main(["search", "q", "--min-similarity", bad], connect=_no_database)


def test_a_blank_question_prints_one_sentence(capsys):
    # the real search refuses before any model or database is used
    assert ingest.main(["search", "   "], connect=_no_database) == 1
    out = capsys.readouterr().out
    assert out == "Type a question to search for.\n"


# --- block i: ingest ask (assumed until block j); a fake scripted model, never Ollama ---


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return llm.Reply(self.replies.pop(0), 1000)


ANSWER = (
    '{"answerable": true, "answer": "Short passage text says it.",'
    ' "citations": [{"chunk_id": 11, "sentence": 1}]}'
)


def test_ask_command_prints_the_answer_and_its_source(monkeypatch, capsys):
    model = ScriptedModel(ANSWER)
    monkeypatch.setattr(ingest, "search", lambda conn, q: _result([_passage(0.79, "Setup")]))
    monkeypatch.setattr(ingest, "answer", lambda q, p: ask.answer(q, p, model=model))
    assert ingest.main(["ask", "What does it say?"], connect=_no_database) == 0
    saved = datetime(2026, 10, 21, 9, 0, tzinfo=UTC).astimezone().strftime("%Y-%m-%d")
    assert capsys.readouterr().out.splitlines() == [
        "Short passage text says it.",
        "",
        "Sources:",
        '1. "Short passage text."',
        f"   llm-wiki - Setup (https://example.test/wiki, saved {saved})",
    ]


def test_ask_command_refuses_without_a_model_call(monkeypatch, capsys):
    model = ScriptedModel()
    monkeypatch.setattr(ingest, "search", lambda conn, q: _result([], 0.40))
    monkeypatch.setattr(ingest, "answer", lambda q, p: ask.answer(q, p, model=model))
    assert ingest.main(["ask", "Who won the 2022 FIFA World Cup?"], connect=_no_database) == 0
    assert capsys.readouterr().out == "I couldn't find this in your saved material.\n"
    assert model.calls == 0


ASK_STATE = (
    "SELECT (SELECT count(*) FROM query_log),"
    " (SELECT array_agg(last_asked_at ORDER BY id) FROM documents)"
)


class SameVectorEmbedder:
    """Fake model: the question gets the same unit vector as the saved chunk (similarity 1)."""

    def query_embed(self, query):
        return iter([UNIT.copy()])


UNIT = np.zeros(384, dtype=np.float32)
UNIT[0] = 1.0


@pytest.mark.db
def test_ask_command_writes_neither_last_asked_at_nor_query_log(conn, empty_db, monkeypatch):
    document = conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
        " content_hash) VALUES ((SELECT id FROM spaces LIMIT 1), 'Never asked', 'text', 'L',"
        " 'text:L', 'h') RETURNING id"
    ).fetchone()[0]
    chunk = conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding)"
        " VALUES (%s, 0, 'Short passage text.', %s) RETURNING id",
        (document, UNIT),
    ).fetchone()[0]
    before = conn.execute(ASK_STATE).fetchone()
    conn.commit()
    model = ScriptedModel(ANSWER.replace('"chunk_id": 11', f'"chunk_id": {chunk}'))
    monkeypatch.setattr(
        ingest, "search", lambda c, q: retrieval.search(c, q, embedder=SameVectorEmbedder())
    )
    monkeypatch.setattr(ingest, "answer", lambda q, p: ask.answer(q, p, model=model))
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert ingest.main(["ask", "What does it say?"], connect=_test_database(empty_db)) == 0
    assert out.getvalue().startswith("Short passage text says it.")
    assert model.calls == 1
    assert conn.execute(ASK_STATE).fetchone() == before
    assert before == (0, [None])
