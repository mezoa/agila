import ast
import hashlib
import json
import statistics
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import psycopg
import pytest

from agila import ask, db, evaluate, llm
from agila.chunking import CACHE_DIR
from agila.embed import QUERY_INSTRUCTION
from agila.evaluate import EvalError, is_hit, normalize, read_hit_phrases, read_questions
from agila.retrieval import Passage, SearchResult
from agila.web import FetchError

FIXTURES = Path(__file__).parent / "fixtures" / "eval"  # made up: never the real golden set
SAVED = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def _passage(text, chunk_id=1, similarity=0.8):
    return Passage(chunk_id, text, None, None, "Title", "source.md", SAVED, similarity)


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _questions_text(lines=None):
    lines = lines or (FIXTURES / "questions.txt").read_text(encoding="utf-8").splitlines()
    return "\n".join(lines) + "\n"


# --- step 2: reading the exam files ---


def test_the_questions_file_gives_20_questions_with_their_half():
    questions = read_questions(FIXTURES / "questions.txt")
    assert len(questions) == 20
    assert questions[0] == evaluate.Question(1, "dev", "How tall is the blue lighthouse?")
    assert questions[1].half == "held-out"
    assert sum(q.half == "dev" for q in questions) == 10


def test_comment_and_blank_lines_and_a_bom_are_ignored(tmp_path):
    text = "﻿# a comment\n\n" + _questions_text()
    assert len(read_questions(_write(tmp_path, "q.txt", text))) == 20


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda lines: lines[:-1], "has 19 questions, not 20"),
        (lambda lines: lines + ["21 | dev | One more?"], "has 21 questions, not 20"),
        (lambda lines: lines[:-1] + ["02 | dev | Again?"], "question 02 is repeated"),
        (lambda lines: lines[:-1] + ["20 | test | Wrong half?"], "must be dev or held-out"),
        (lambda lines: lines[:-1] + ["20 | dev"], "not in the expected format"),
        (lambda lines: lines[:-1] + ["xx | dev | No number?"], "not in the expected format"),
        (lambda lines: lines[:-1] + ["20 | dev |   "], "not in the expected format"),
    ],
)
def test_a_bad_questions_file_is_refused_with_one_sentence(tmp_path, change, message):
    lines = (FIXTURES / "questions.txt").read_text(encoding="utf-8").splitlines()
    path = _write(tmp_path, "q.txt", _questions_text(change(lines)))
    with pytest.raises(EvalError, match=message):
        read_questions(path)


def test_a_missing_file_is_one_sentence(tmp_path):
    with pytest.raises(EvalError, match="File not found"):
        read_questions(tmp_path / "nope.txt")


def test_the_phrases_file_gives_seven_answerable_questions_per_half():
    questions = read_questions(FIXTURES / "questions.txt")
    phrases = read_hit_phrases(FIXTURES / "hit-phrases.txt", questions)
    assert len(phrases) == 14
    assert phrases[1] == "thirty metres tall"
    assert 15 not in phrases  # no line: unanswerable


def test_a_phrase_may_contain_a_bar(tmp_path):
    questions = read_questions(FIXTURES / "questions.txt")
    text = (
        (FIXTURES / "hit-phrases.txt")
        .read_text(encoding="utf-8")
        .replace("01 | thirty metres tall", "01 | thirty | metres")
    )
    assert read_hit_phrases(_write(tmp_path, "p.txt", text), questions)[1] == "thirty | metres"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda text: text.replace("14 | four metres deep", ""), "6 phrases for the held-out"),
        (lambda text: text + "15 | extra\n", "8 phrases for the dev"),
        (lambda text: text + "01 | again\n", "question 01 is repeated"),
        (lambda text: text + "99 | nowhere\n", "no question 99"),
        (lambda text: text + "16 |   \n", "not in the expected format"),
    ],
)
def test_a_bad_phrases_file_is_refused_without_showing_a_phrase(tmp_path, change, message):
    questions = read_questions(FIXTURES / "questions.txt")
    text = change((FIXTURES / "hit-phrases.txt").read_text(encoding="utf-8"))
    with pytest.raises(EvalError, match=message) as caught:
        read_hit_phrases(_write(tmp_path, "p.txt", text), questions)
    assert "metres" not in str(caught.value) and "again" not in str(caught.value)


def test_normalize_lowercases_and_drops_all_whitespace():
    assert normalize("  Thirty\tMetres\n tall ") == "thirtymetrestall"


def test_a_phrase_split_by_a_line_break_or_in_other_case_is_still_a_hit():
    passages = [_passage("The lighthouse is THIRTY\nmetres   tall and blue.")]
    assert is_hit("thirty metres tall", passages)


def test_a_phrase_in_the_fourth_passage_or_missing_is_a_miss():
    passages = [_passage("nothing"), _passage("nothing"), _passage("nothing")]
    assert not is_hit("thirty metres tall", passages)
    assert not is_hit("thirty metres tall", passages + [_passage("thirty metres tall")])
    third = [_passage("x"), _passage("x"), _passage("thirty metres tall")]
    assert is_hit("thirty metres tall", third)


# --- step 3: scoring ---


def _outcome(number, half, answerable, best, hit=False):
    sims = () if best is None else (best, best - 0.01, best - 0.02)
    return evaluate.Outcome(evaluate.Question(number, half, "Q?"), answerable, hit, sims)


def test_score_counts_hits_refusals_and_false_refusals_per_half():
    outcomes = [
        _outcome(1, "dev", True, 0.80, hit=True),
        _outcome(2, "dev", True, 0.65, hit=True),  # a hit, but below the threshold
        _outcome(3, "held-out", True, 0.75, hit=False),
        _outcome(4, "dev", False, 0.55),
        _outcome(5, "held-out", False, 0.72),  # let through
        _outcome(6, "held-out", False, None),  # empty library: refused
    ]
    s = evaluate.score(outcomes, 0.70)
    assert (s.answerable, s.hits, s.hits_by_half) == (3, 2, {"dev": 2, "held-out": 0})
    assert (s.unanswerable, s.refused, s.refused_by_half) == (3, 2, {"dev": 1, "held-out": 1})
    assert s.false_refusals == 1


def test_a_score_exactly_at_the_threshold_is_not_refused():
    s = evaluate.score([_outcome(1, "dev", False, 0.70), _outcome(2, "dev", True, 0.70)], 0.70)
    assert (s.refused, s.false_refusals) == (0, 0)


def test_gap_is_lowest_answerable_best_minus_highest_unanswerable_best():
    outcomes = [_outcome(1, "dev", True, 0.786), _outcome(2, "dev", True, 0.857)]
    outcomes += [_outcome(3, "dev", False, 0.603), _outcome(4, "dev", False, 0.402)]
    assert evaluate.gap(outcomes) == pytest.approx(0.183)
    assert evaluate.gap(outcomes[:2]) is None


def test_with_no_overlap_the_proposal_is_the_middle_of_the_gap():
    # The block h numbers: unanswerable up to 0.603, answerable from 0.786 -> 0.70 (V58).
    outcomes = [_outcome(1, "dev", True, 0.786), _outcome(2, "dev", True, 0.857)]
    outcomes += [_outcome(3, "dev", False, 0.603), _outcome(4, "dev", False, 0.511)]
    assert evaluate.propose_threshold(outcomes) == (0.70, 0)


def test_with_overlap_the_highest_run_with_fewest_errors_wins():
    # Answerable 0.80 and 0.62, unanswerable 0.70 and 0.50. One error is the fewest, and it
    # happens in two runs: 0.51 to 0.62 (lets 0.70 through) and 0.71 to 0.80 (refuses 0.62).
    # Ties lean toward refusing, so the higher run wins: its middle, rounded up, is 0.76.
    outcomes = [_outcome(1, "dev", True, 0.80), _outcome(2, "dev", True, 0.62)]
    outcomes += [_outcome(3, "dev", False, 0.70), _outcome(4, "dev", False, 0.50)]
    assert evaluate.propose_threshold(outcomes) == (0.76, 1)
    s = evaluate.score(outcomes, 0.76)
    assert (s.false_refusals, s.refused) == (1, 2)


# --- step 4: the query prefix through the embedder argument ---


class RecordingEmbedder:
    def __init__(self):
        self.queries, self.passages = [], []

    def query_embed(self, query):
        self.queries.append(query)
        vector = np.zeros(384, dtype=np.float32)
        vector[0] = 1.0
        return iter([vector])

    def passage_embed(self, texts):
        texts = list(texts)
        self.passages.extend(texts)
        return iter([np.ones(384, dtype=np.float32) for _ in texts])


class EmptyLibrary:
    """Just enough of a connection for the real `retrieval.search`: no rows, nothing written."""

    read_only = None

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=None):
        return self

    def fetchall(self):
        return []


def test_the_evaluation_forces_each_prefix_setting_through_the_real_search():
    # Since block l step 10 the app adds the prefix by default, so the evaluation must ask for
    # each setting explicitly; a wrapper that added it again would double it.
    questions = [evaluate.Question(1, "dev", "  What is it?  ")]
    seen = {}
    for setting in (False, True, None):
        embedder = RecordingEmbedder()
        evaluate.run_retrieval(
            EmptyLibrary(), questions, {}, embedder=embedder, with_instruction=setting
        )
        seen[setting] = embedder.queries
    assert seen[False] == ["What is it?"]
    assert seen[True] == seen[None] == [QUERY_INSTRUCTION + "What is it?"]


# --- step 5: the eval database, by name only ---


class FakeConnect:
    """Records every database opened and every SQL sent; opens nothing."""

    def __init__(self):
        self.opened, self.sql = [], []

    def __call__(self, dbname=None, register=True, connect_timeout=None):
        self.opened.append(dbname)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)


@pytest.fixture
def fake_connect(monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", "agila")
    monkeypatch.setattr(evaluate.db, "migrate", lambda conn: ["0001_init.sql"])
    return FakeConnect()


def test_open_eval_opens_only_agila_eval(fake_connect):
    evaluate.open_eval(fake_connect)
    assert fake_connect.opened == ["agila_eval"]


def test_create_drops_and_creates_agila_eval_from_postgres_then_migrates(fake_connect):
    assert evaluate.create_eval_db(fake_connect) == ["0001_init.sql"]
    assert fake_connect.opened == ["postgres", "postgres", "agila_eval"]
    assert fake_connect.sql == [
        "DROP DATABASE IF EXISTS agila_eval WITH (FORCE)",
        "CREATE DATABASE agila_eval",
    ]


def test_drop_names_only_agila_eval(fake_connect):
    evaluate.drop_eval_db(fake_connect)
    assert fake_connect.opened == ["postgres"]
    assert fake_connect.sql == ["DROP DATABASE IF EXISTS agila_eval WITH (FORCE)"]


@pytest.mark.parametrize("name", ["agila", "AGILA", "Agila", "postgres", "agila_test", "", "x"])
@pytest.mark.parametrize("action", [evaluate.create_eval_db, evaluate.drop_eval_db])
def test_the_guard_refuses_any_other_name_before_any_sql(fake_connect, action, name):
    with pytest.raises(EvalError, match="only uses the database agila_eval"):
        action(fake_connect, name=name)
    assert fake_connect.opened == [] and fake_connect.sql == []


def test_the_guard_refuses_agila_eval_if_it_is_the_real_library(fake_connect, monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", "AGILA_EVAL")
    for action in (evaluate.open_eval, evaluate.create_eval_db, evaluate.drop_eval_db):
        with pytest.raises(EvalError):
            action(fake_connect)
    assert fake_connect.opened == []


def test_no_sql_in_the_module_names_the_real_library():
    source = Path(evaluate.__file__).read_text(encoding="utf-8")
    assert "DATABASE agila " not in source and 'DATABASE agila"' not in source
    assert 'dbname="agila"' not in source and "dbname='agila'" not in source


# --- step 6: freezing the web pages (U51), fake fetcher, no network ---

URLS = ["https://one.test/a", "https://two.test/b"]
WORDS = lambda text: len(text.split())  # noqa: E731  (a fast stand-in for the model's tokenizer)


def _page(marker):
    """The made-up article fixture with Windows line endings and non-ASCII text added."""
    html = (Path(__file__).parent / "fixtures" / "article.html").read_text(encoding="utf-8")
    html = html.replace("</body>", f"<p>Café ñame {marker} ends here.</p></body>")
    return html.replace("\n", "\r\n")


def test_freeze_stores_each_page_once_with_a_manifest(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return _page(url)

    names = evaluate.freeze(URLS, tmp_path, fetch, WORDS, today=date(2026, 10, 26))
    assert names == ["web-01.html", "web-02.html"]
    assert calls == URLS  # each page fetched exactly once
    raw = (tmp_path / "web-01.html").read_bytes()
    assert raw.decode("utf-8") == _page(URLS[0])  # no line-ending change, UTF-8 kept
    manifest = json.loads((tmp_path / "web-pages.json").read_text(encoding="utf-8"))
    assert manifest[0] == {
        "url": URLS[0],
        "file": "web-01.html",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fetched": "2026-10-26",
    }
    stored = evaluate.web_chunks(URLS[1], (tmp_path / "web-02.html").read_text("utf-8"), WORDS)
    assert stored == evaluate.web_chunks(URLS[1], _page(URLS[1]), WORDS)


def test_freezing_twice_is_refused_and_changes_nothing(tmp_path):
    evaluate.freeze(URLS, tmp_path, _page, WORDS)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(EvalError, match="already frozen"):
        evaluate.freeze(URLS, tmp_path, lambda url: "<p>other</p>", WORDS)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_a_failed_download_writes_nothing(tmp_path):
    def fetch(url):
        if url == URLS[1]:
            raise FetchError("The page answered with status 404.")
        return _page(url)

    with pytest.raises(EvalError, match="Web page 2 could not be frozen: The page answered"):
        evaluate.freeze(URLS, tmp_path, fetch, WORDS)
    assert list(tmp_path.iterdir()) == []


def test_a_thin_page_writes_nothing(tmp_path):
    empty = (Path(__file__).parent / "fixtures" / "empty.html").read_text(encoding="utf-8")
    with pytest.raises(EvalError, match="Web page 1 could not be frozen"):
        evaluate.freeze(URLS, tmp_path, lambda url: empty, WORDS)
    assert list(tmp_path.iterdir()) == []


def test_a_stored_copy_with_other_chunks_is_removed(tmp_path, monkeypatch):
    real = evaluate.web_chunks
    seen = []

    def drifting(url, html, count_tokens=None):
        seen.append(url)
        chunks = real(url, html, count_tokens)
        return chunks + ["extra"] if len(seen) > len(URLS) else chunks  # read-back differs

    monkeypatch.setattr(evaluate, "web_chunks", drifting)
    with pytest.raises(EvalError, match="web-01.html gives other chunks"):
        evaluate.freeze(URLS, tmp_path, _page, WORDS)
    assert list(tmp_path.iterdir()) == []


def test_read_urls_skips_comments_and_blank_lines(tmp_path):
    path = _write(tmp_path, "w.txt", "# note\n\nhttps://one.test/a\n  https://two.test/b  \n")
    assert evaluate.read_urls(path) == URLS


# --- step 7: building the library from the frozen files (database: agila_test only) ---

needs_model = pytest.mark.skipif(
    not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed"
)  # the save code counts tokens with the real tokenizer


def _library(tmp_path):
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "01-harbour.md").write_text(
        "# Harbour notes\n\n## Ferry\n\nThe ferry is painted bright red.\n", encoding="utf-8"
    )
    (folder / "02-village.txt").write_text(
        "The village clock is kept by the retired teacher.\r\n", encoding="utf-8"
    )
    evaluate.freeze(URLS[:1], folder, _page, WORDS)
    return folder


@needs_model
@pytest.mark.db
def test_build_saves_markdown_text_and_frozen_pages_with_no_network(conn, tmp_path):
    folder = _library(tmp_path)
    documents, chunks = evaluate.build(conn, folder, URLS[:1], embedder=RecordingEmbedder())
    rows = conn.execute(
        "SELECT source_type, title, source_label, source_url FROM documents ORDER BY id"
    ).fetchall()
    assert rows == [
        ("markdown", "Harbour notes", "01-harbour.md", None),
        ("text", "02-village", "02-village.txt", None),
        ("web", "How Agila Saves a Page", URLS[0], URLS[0]),
    ]
    assert documents == 3 and chunks >= 3


@needs_model
@pytest.mark.db
def test_a_changed_frozen_page_stops_the_build_before_anything_is_saved(conn, tmp_path):
    folder = _library(tmp_path)
    page = folder / "web-01.html"
    page.write_bytes(page.read_bytes() + b"<!-- edited -->")
    with pytest.raises(EvalError, match="web-01.html has changed since it was frozen"):
        evaluate.build(conn, folder, URLS[:1], embedder=RecordingEmbedder())
    assert conn.execute("SELECT count(*) FROM documents").fetchone() == (0,)


def test_a_library_that_was_never_frozen_is_refused(tmp_path):
    with pytest.raises(EvalError, match="run evaluate freeze first"):
        evaluate.build(None, tmp_path, URLS)


def test_a_manifest_for_other_links_is_refused(tmp_path):
    evaluate.freeze(URLS[:1], tmp_path, _page, WORDS)
    with pytest.raises(EvalError, match="does not list the links of web-sources.txt"):
        evaluate.build(None, tmp_path, URLS)


# --- step 8: retrieval and answer runs never write (FR35, U50); database: agila_test only ---

E0 = np.zeros(384, dtype=np.float32)
E0[0] = 1.0
FIXED = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


class ScriptedModel:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def chat(self, messages):
        self.calls += 1
        return llm.Reply(self.reply, 1000)


def _saved_document(conn, title, last_asked_at):
    document_id = conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
        " content_hash, last_asked_at) VALUES ((SELECT id FROM spaces LIMIT 1), %s, 'text',"
        " %s, %s, 'h', %s) RETURNING id",
        (title, title, f"text:{title}", last_asked_at),
    ).fetchone()[0]
    chunk_id = conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding) VALUES (%s, 0, %s, %s)"
        " RETURNING id",
        (document_id, "The lighthouse is thirty metres tall. It is blue.", E0),
    ).fetchone()[0]
    return document_id, chunk_id


@pytest.mark.db
def test_an_evaluation_run_changes_neither_last_asked_at_nor_query_log(conn):
    _saved_document(conn, "never asked", None)
    _, chunk_id = _saved_document(conn, "asked once", FIXED)
    before = conn.execute("SELECT id, last_asked_at FROM documents ORDER BY id").fetchall()
    conn.commit()  # the run needs an idle connection (U50): a SELECT after this would open one
    questions = read_questions(FIXTURES / "questions.txt")
    phrases = read_hit_phrases(FIXTURES / "hit-phrases.txt", questions)

    run = evaluate.run_retrieval(conn, questions, phrases, embedder=RecordingEmbedder())
    assert run.outcomes[0].hit and run.outcomes[0].best == pytest.approx(1.0)
    reply = json.dumps(
        {
            "answerable": True,
            "answer": "Thirty metres.",
            "citations": [{"chunk_id": chunk_id, "sentence": 1}],
        }
    )
    model = ScriptedModel(reply)
    answers = evaluate.run_answers(
        conn, questions[:3], 0.70, embedder=RecordingEmbedder(), model=model
    )
    assert [a.kind for _, a, _ in answers] == ["answer"] * 3 and model.calls == 3

    after = conn.execute("SELECT id, last_asked_at FROM documents ORDER BY id").fetchall()
    assert after == before
    assert conn.execute("SELECT count(*) FROM query_log").fetchone() == (0,)


@pytest.mark.db
def test_after_a_run_the_connection_refuses_writes(conn):
    _saved_document(conn, "a note", None)
    conn.commit()
    evaluate.run_retrieval(
        conn, [evaluate.Question(1, "dev", "Q?")], {}, embedder=RecordingEmbedder()
    )
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute(
            "INSERT INTO query_log (channel, status, seconds) VALUES ('cli', 'refused', 0.1)"
        )


def test_timings_split_into_the_cold_search_and_the_next_ten():
    ticks = iter(range(100))
    questions = [evaluate.Question(n, "dev", "Q?") for n in range(1, 14)]

    class Conn:
        read_only = None

    def search(conn, question, min_similarity, embedder, with_instruction):
        assert min_similarity == -1.0  # M1: the raw top 3, no threshold
        return SearchResult([], None, min_similarity)

    run = evaluate.run_retrieval(Conn(), questions, {}, search=search, clock=lambda: next(ticks))
    assert run.cold == 1 and run.warm == [1] * 10 and len(run.seconds) == 13


def _is_banned_name(name: str) -> bool:
    return name == "ask_question" or name.startswith("record_")


def banned_uses(source: str) -> list[str]:
    """Every way the source could reach the ask flow of `questions.py` (FR35). A local variable
    called `questions` is fine: only the module is banned."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agila.questions" or alias.name.startswith("agila.questions."):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "agila.questions" or module.startswith("agila.questions."):
                found.append(f"from {module} import ...")
            for alias in node.names:
                if module == "agila" and alias.name == "questions":
                    found.append("from agila import questions")
                if _is_banned_name(alias.name):
                    found.append(f"import of {alias.name}")
        elif isinstance(node, ast.Name) and _is_banned_name(node.id):
            found.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and _is_banned_name(node.attr):
            found.append(f"attribute {node.attr}")
    return found


def test_the_evaluation_never_reaches_the_ask_flow():
    assert banned_uses(Path(evaluate.__file__).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        "import agila.questions",
        "import agila.questions as q",
        "from agila import questions",
        "from agila import db, questions as q",
        "from agila.questions import STATUS",
        "from agila.questions import ask_question",
        "result = ask_question(conn, 'Q?', 'cli')",
        "import agila\nagila.questions.ask_question(conn, 'Q?', 'cli')",
        "record_ask(conn)",
        "log.record_question(1)",
    ],
)
def test_the_ask_flow_check_catches_each_banned_form(source):
    assert banned_uses(source) != []


def test_the_ask_flow_check_allows_a_local_variable_called_questions():
    source = "questions = read_questions(path)\nfor q in questions:\n    record = q\n"
    assert banned_uses(source) == []


# --- step 9: the dev-only actions, a fresh connection per run, the command ---


class EvalConnect(FakeConnect):
    """A fake connection that also takes `read_only`; each call is one fresh connection."""

    read_only = None


@pytest.fixture
def recorded_searches(monkeypatch):
    seen = []

    def search(conn, question, min_similarity, embedder, with_instruction):
        seen.append((question, with_instruction))
        score = 0.9 if "lighthouse" in question else 0.5
        found = [_passage("The lighthouse is thirty metres tall.", similarity=score)]
        return SearchResult(found, score, min_similarity)

    monkeypatch.setattr(evaluate.retrieval, "search", search)
    return seen


def test_prefix_runs_only_dev_questions_twice_on_two_fresh_connections(
    recorded_searches, fake_connect, capsys
):
    connect = EvalConnect()
    code = evaluate.main(["prefix"], connect=connect, folder=FIXTURES, embedder=RecordingEmbedder())
    assert code == 0
    questions = read_questions(FIXTURES / "questions.txt")
    dev = [q.text for q in questions if q.half == "dev"]
    assert [q for q, _ in recorded_searches] == dev + dev  # never a held-out question
    assert [s for _, s in recorded_searches] == [False] * 10 + [True] * 10  # forced each way
    assert connect.opened == ["agila_eval", "agila_eval"]
    out = capsys.readouterr().out
    assert "01  yes | hit yes best 0.900 | hit yes best 0.900" in out
    assert "Without prefix: dev hits 1 of 7, gap +0.000, proposed threshold" in out
    assert "With prefix: dev hits 1 of 7" in out
    assert "02 " not in out and "metres" not in out  # no held-out row, no phrase


@pytest.mark.parametrize(
    ("flags", "setting", "word"),
    [([], True, "with"), (["--prefix"], True, "with"), (["--no-prefix"], False, "without")],
)
def test_threshold_runs_only_dev_questions_on_one_fresh_connection(
    recorded_searches, fake_connect, capsys, flags, setting, word
):
    # No flag = the app's setting, which is on since block l step 10.
    connect = EvalConnect()
    argv = ["threshold", *flags]
    assert evaluate.main(argv, connect=connect, folder=FIXTURES, embedder=RecordingEmbedder()) == 0
    dev = {q.text for q in read_questions(FIXTURES / "questions.txt") if q.half == "dev"}
    assert {q for q, _ in recorded_searches} == dev and len(recorded_searches) == 10
    assert {s for _, s in recorded_searches} == {setting}
    assert connect.opened == ["agila_eval"]
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"Dev half only, {word} the query prefix, best first:"
    assert lines[1] == "0.900  answerable    Q01"
    assert lines[-1].startswith("Proposed threshold: ")


def test_drop_says_what_it_dropped(fake_connect, capsys):
    assert evaluate.main(["drop"], connect=fake_connect) == 0
    assert fake_connect.opened == ["postgres"]
    assert capsys.readouterr().out == "Dropped agila_eval.\n"


def test_freeze_and_build_through_the_command(tmp_path, fake_connect, monkeypatch, capsys):
    folder = tmp_path / "eval"
    (folder / "library").mkdir(parents=True)
    (folder / "web-sources.txt").write_text("# links\n" + "\n".join(URLS) + "\n", "utf-8")
    monkeypatch.setattr(evaluate, "chunk_document", _word_chunks(evaluate.chunk_document))
    assert evaluate.main(["freeze"], connect=fake_connect, folder=folder, fetch=_page) == 0
    assert "Froze 2 pages into" in capsys.readouterr().out
    assert fake_connect.opened == []  # freezing touches no database
    assert evaluate.main(["freeze"], connect=fake_connect, folder=folder, fetch=_page) == 1
    assert "already frozen" in capsys.readouterr().out

    built = []
    monkeypatch.setattr(
        evaluate, "build", lambda conn, library, urls, embedder: built.append(urls) or (9, 120)
    )
    assert evaluate.main(["build"], connect=fake_connect, folder=folder) == 0
    assert built == [URLS]
    assert fake_connect.opened == ["postgres", "postgres", "agila_eval", "agila_eval"]
    assert capsys.readouterr().out == (
        "Built agila_eval: 9 documents, 120 chunks."
        " Web pages: stored chunks match the frozen HTML (2 of 2).\n"
    )


def _word_chunks(real):
    """The real chunker with a word counter, so the command test needs no model."""
    return lambda title, text, is_markdown, count_tokens=None: real(title, text, is_markdown, WORDS)


def test_a_missing_exam_file_is_one_sentence(tmp_path, fake_connect, capsys):
    assert evaluate.main(["threshold"], connect=EvalConnect(), folder=tmp_path) == 1
    assert capsys.readouterr().out.startswith("File not found: ")


def test_an_unreachable_eval_database_is_one_sentence(monkeypatch, capsys):
    def down(**kwargs):
        raise psycopg.OperationalError("connection refused")

    assert evaluate.main(["threshold"], connect=down, folder=FIXTURES) == 1
    assert capsys.readouterr().out.startswith("Cannot open the database agila_eval.")


def test_no_action_prints_the_usage_and_exits_2(capsys):
    assert evaluate.main([]) == 2
    assert "freeze,build,prefix,threshold,retrieval,answers,drop" in capsys.readouterr().err


# --- steps 11 and 12: the retrieval and answers actions (fakes; no model, no network) ---


def _exam(tmp_path):
    """A copy of the made-up exam in its own folder, so a baseline or sheet lands in tmp_path."""
    folder = tmp_path / "eval"
    folder.mkdir()
    for name in ("questions.txt", "hit-phrases.txt"):
        (folder / name).write_bytes((FIXTURES / name).read_bytes())
    return folder


@pytest.fixture
def exam_search(monkeypatch):
    """Scripted search over the made-up exam. Answerable questions find their phrase at 0.9,
    unanswerable ones score 0.5; `misses` and `scores` change single questions."""
    questions = read_questions(FIXTURES / "questions.txt")
    phrases = read_hit_phrases(FIXTURES / "hit-phrases.txt", questions)
    by_text = {q.text: q.number for q in questions}
    script = {"misses": set(), "scores": {}, "calls": []}

    def search(conn, question, min_similarity, embedder=None, with_instruction=None):
        number = by_text[question]
        script["calls"].append((number, min_similarity))
        found = number in phrases and number not in script["misses"]
        default = 0.9 if number in phrases else 0.5
        score = script["scores"].get(number, default)
        # Two real sentences: the app's splitter joins pieces under 3 words to the next one.
        text = f"These are the notes. {phrases[number]} indeed." if found else "Nothing here."
        passages = [_passage(text, chunk_id=number, similarity=score)]
        return SearchResult([p for p in passages if score >= min_similarity], score, min_similarity)

    monkeypatch.setattr(evaluate.retrieval, "search", search)
    monkeypatch.setattr(evaluate, "_git_commit", lambda: "abc1234")
    return script


def _ticks(step=1.0):
    clock = iter(x * step for x in range(10_000))
    return lambda: next(clock)


def _retrieval(folder, *flags, connect=None):
    return evaluate.main(
        ["retrieval", *flags],
        connect=connect or EvalConnect(),
        folder=folder,
        clock=_ticks(),
        today=date(2026, 10, 26),
    )


def test_the_first_full_run_saves_a_baseline_of_numbers_only(tmp_path, exam_search, capsys):
    folder, connect = _exam(tmp_path), EvalConnect()
    assert _retrieval(folder, "--save-baseline", connect=connect) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "All 20 questions, raw top 3, query prefix on, threshold 0.68.",
        "M1 hit@3: 14 of 14 (1.00); dev 7 of 7, held-out 7 of 7.",
        "False refusals (answerable below 0.68): 0 of 14.",
        "M2 refused with no model call: 6 of 6; dev 3 of 3, held-out 3 of 3.",
        "M3 time to passages: cold 1.00 s, median 1.000 s over 10 warm searches.",
        f"Saved {folder / 'baseline.json'}.",
    ]
    assert sorted(n for n, _ in exam_search["calls"]) == list(range(1, 21))  # held-out included
    assert {m for _, m in exam_search["calls"]} == {-1.0}  # M1: raw top 3, no threshold
    assert connect.opened == ["agila_eval"] and connect.read_only is True
    text = (folder / "baseline.json").read_text(encoding="utf-8")
    saved = json.loads(text)
    assert (saved["hits"], saved["refused"], saved["false_refusals"]) == (14, 6, 0)
    assert (saved["hits_dev"], saved["hits_held_out"]) == (7, 7)
    assert (saved["threshold"], saved["query_prefix"], saved["git_commit"]) == (
        0.68,
        True,
        "abc1234",
    )
    assert saved["embedding_model"] == "BAAI/bge-small-en-v1.5" and saved["date"] == "2026-10-26"
    for q in read_questions(FIXTURES / "questions.txt"):
        assert q.text not in text  # no question text
    assert "metres" not in text and "notes" not in text  # no phrase, no passage text


def test_the_same_result_again_is_not_below_the_baseline(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    _retrieval(folder, "--save-baseline")
    capsys.readouterr()
    assert _retrieval(folder) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "Not below the baseline baseline.json: hits 14 (baseline 14), refusals 6 (baseline 6)."
    )


def test_one_hit_fewer_exits_1_with_one_sentence(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    _retrieval(folder, "--save-baseline")
    exam_search["misses"].add(2)
    capsys.readouterr()
    assert _retrieval(folder) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "hit@3 dropped: 13, baseline 14."


def test_one_refusal_fewer_exits_1_with_one_sentence(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    _retrieval(folder, "--save-baseline")
    exam_search["scores"][16] = 0.75  # an unanswerable question now passes the threshold
    capsys.readouterr()
    assert _retrieval(folder) == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "Refusals of unanswerable questions dropped: 5, baseline 6."
    )


def test_a_better_result_than_the_baseline_exits_0(tmp_path, exam_search):
    folder = _exam(tmp_path)
    exam_search["misses"].add(2)
    _retrieval(folder, "--save-baseline")
    exam_search["misses"].clear()
    assert _retrieval(folder) == 0


def test_the_raised_copy_of_command_11_makes_the_run_fail(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    _retrieval(folder, "--save-baseline")
    (folder / "runs").mkdir()
    # The one-line helper of plan command 11, run here on the test's own copy.
    b = json.loads((folder / "baseline.json").read_text(encoding="utf-8"))
    b["hits"] += 1
    (folder / "runs" / "baseline-raised.json").write_text(json.dumps(b, indent=2), "utf-8")
    capsys.readouterr()
    assert _retrieval(folder, "--baseline", str(folder / "runs" / "baseline-raised.json")) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "hit@3 dropped: 14, baseline 15."


def test_false_refusals_are_counted_but_do_not_fail_the_run(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    _retrieval(folder, "--save-baseline")
    exam_search["scores"][3] = 0.60  # still a hit in the raw top 3, but below 0.68
    capsys.readouterr()
    assert _retrieval(folder) == 0
    assert "False refusals (answerable below 0.68): 1 of 14." in capsys.readouterr().out


def test_without_a_baseline_nothing_runs_unless_it_is_being_saved(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    assert _retrieval(folder) == 1
    assert capsys.readouterr().out.startswith(f"No baseline at {folder / 'baseline.json'};")
    assert exam_search["calls"] == []


def test_an_existing_baseline_is_never_overwritten(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    (folder / "baseline.json").write_text('{"hits": 3}', encoding="utf-8")
    assert _retrieval(folder, "--save-baseline") == 1
    assert "already exists; nothing was run" in capsys.readouterr().out
    assert exam_search["calls"] == []
    assert (folder / "baseline.json").read_text(encoding="utf-8") == '{"hits": 3}'


def test_an_unreadable_baseline_is_one_sentence(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    (folder / "baseline.json").write_text('{"hits": 3}', encoding="utf-8")  # no "refused"
    assert _retrieval(folder) == 1
    assert (
        capsys.readouterr()
        .out.splitlines()[-1]
        .endswith("is not a readable baseline; nothing was compared.")
    )


class ScriptedReplies:
    """Fake model: the next scripted reply on each call (or the last one again)."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def chat(self, messages):
        self.calls += 1
        reply = self.replies[min(self.calls, len(self.replies)) - 1]
        return llm.Reply(reply, 1000)


def _reply(answerable, citations=()):
    return json.dumps(
        {
            "answerable": answerable,
            "answer": "It is | thirty metres." if answerable else "",
            "citations": [{"chunk_id": c, "sentence": s} for c, s in citations],
        }
    )


def _answers(folder, model, connect=None, clock=None):
    return evaluate.main(
        ["answers"],
        connect=connect or EvalConnect(),
        folder=folder,
        model=model,
        clock=clock or _ticks(),
        today=date(2026, 10, 26),
        version=lambda: "0.40.8",
    )


def test_answers_writes_a_grading_sheet_with_one_row_per_citation(tmp_path, exam_search, capsys):
    folder, connect = _exam(tmp_path), EvalConnect()
    replies = [_reply(True, [(1, 1), (1, 2)]), _reply(True, [(2, 1)]), _reply(False)]
    replies += [_reply(True, [(n, 1)]) for n in range(4, 15)]
    model = ScriptedReplies(replies)
    times = iter([0.0, 50.0] + [x for n in range(13) for x in (100.0 + 10 * n, 102.0 + 10 * n)])
    assert _answers(folder, model, connect, clock=lambda: next(times)) == 0
    assert sorted(n for n, _ in exam_search["calls"]) == list(range(1, 15))  # answerable only
    assert {m for _, m in exam_search["calls"]} == {0.68}  # the frozen threshold
    assert connect.opened == ["agila_eval"] and connect.read_only is True
    assert model.calls == 14
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Q01  dev       answer    citations 2  model calls 1  50.0 s"
    assert out[2] == "Q03  dev       refusal   citations 0  model calls 1  2.0 s"
    sheet = folder / "runs" / "grading-2026-10-26.md"
    assert out[-2] == (
        "Cold first answer 50.0 s. M4: median 2.0 s, slowest 2.0 s over 10 warm answers that"
        " called the model (10 of 14 questions; the cold one and 0 with no model call left out)."
        " Ollama 0.40.8."
    )
    assert out[-1] == f"Grading sheet: {sheet}"
    lines = sheet.read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line[:2] == "| " and line[2:4].isdigit()]  # one per Q row
    assert rows[0] == "| 01 | dev | It is \\| thirty metres. | 1:1 | These are the notes. | | | |"
    assert rows[1] == (
        "| 01 | dev | It is \\| thirty metres. | 1:2 | thirty metres tall indeed. | | | |"
    )
    assert rows[3] == "| 03 | dev | no answer (refusal) | - | - | - | - | |"
    assert len(rows) == 2 + 1 + 1 + 11  # one row per citation, one for the refusal


def test_answers_never_overwrites_a_grading_sheet(tmp_path, exam_search, capsys):
    folder = _exam(tmp_path)
    sheet = folder / "runs" / "grading-2026-10-26.md"
    sheet.parent.mkdir()
    sheet.write_text("graded by hand", encoding="utf-8")
    model = ScriptedReplies([_reply(False)])
    assert _answers(folder, model) == 1
    assert "already exists; nothing was run" in capsys.readouterr().out
    assert model.calls == 0 and exam_search["calls"] == []
    assert sheet.read_text(encoding="utf-8") == "graded by hand"


# --- steps 11 and 12 through the command on the throwaway database (agila_test only) ---


@pytest.mark.db
def test_both_actions_write_nothing_to_the_library_they_read(conn, empty_db, tmp_path):
    """The command opens `agila_eval` by name; here that name is redirected to `agila_test`."""
    _saved_document(conn, "never asked", None)
    _, chunk_id = _saved_document(conn, "asked once", FIXED)
    before = conn.execute("SELECT id, last_asked_at FROM documents ORDER BY id").fetchall()
    conn.commit()
    asked = []

    def to_test_database(dbname=None, register=True, connect_timeout=None):
        asked.append(dbname)
        return db.connect(dbname=empty_db, register=register)

    folder = _exam(tmp_path)
    common = {"folder": folder, "embedder": RecordingEmbedder(), "today": date(2026, 10, 26)}
    code = evaluate.main(["retrieval", "--save-baseline"], connect=to_test_database, **common)
    assert code == 0
    assert json.loads((folder / "baseline.json").read_text("utf-8"))["hits"] == 1
    model = ScriptedReplies([_reply(True, [(chunk_id, 1)])])
    code = evaluate.main(
        ["answers"], connect=to_test_database, model=model, version=lambda: None, **common
    )
    assert code == 0 and model.calls == 14
    assert asked == ["agila_eval", "agila_eval"]  # one fresh connection per run
    after = conn.execute("SELECT id, last_asked_at FROM documents ORDER BY id").fetchall()
    assert after == before
    assert conn.execute("SELECT count(*) FROM query_log").fetchone() == (0,)


# --- M4 counts only answers that called the model (bug of 2026-10-26, DEVIATIONS 44) ---

# Seconds per question in the real run of 2026-10-26 (Q01 is the cold one; its real time is not
# needed here). Q03, Q04 and Q05 were refused by the threshold: no model call, 0.0 s.
RUN_SECONDS = {1: 40.0, 2: 12.9, 3: 0.0, 4: 0.0, 5: 0.0, 6: 6.4, 7: 4.6, 8: 1.9, 9: 11.2}
RUN_SECONDS |= {10: 9.9, 11: 11.1, 12: 9.1, 13: 14.4, 14: 15.6}
REFUSED_BY_THRESHOLD = {3, 4, 5}


def test_m4_leaves_out_threshold_refusals_in_the_middle_of_the_run():
    results = []
    for number, seconds in RUN_SECONDS.items():
        calls = 0 if number in REFUSED_BY_THRESHOLD else 1
        kind = "refusal" if calls == 0 else "answer"
        result = ask.Answer(kind, "", None, (), (), calls)
        results.append((evaluate.Question(number, "dev", "Q?"), result, seconds))
    cold, warm = evaluate.m4_rows(results)
    assert cold == 40.0
    assert len(warm) == 10 and 0.0 not in warm
    assert statistics.median(warm) == pytest.approx(10.5) and max(warm) == 15.6
    # The old rule (the 10 rows after the first, whatever they were) gave the wrong numbers.
    old = [s for _, _, s in results][1:11]
    assert statistics.median(old) == pytest.approx(5.5) and max(old) == 12.9


def test_the_answers_action_prints_m4_over_the_warm_model_calls_only(tmp_path, exam_search, capsys):
    for number in REFUSED_BY_THRESHOLD:
        exam_search["scores"][number] = 0.60  # below 0.68: no passages, no model call
    called = [n for n in RUN_SECONDS if n not in REFUSED_BY_THRESHOLD]
    model = ScriptedReplies([_reply(True, [(n, 1)]) for n in called])
    ticks = []
    for n, seconds in RUN_SECONDS.items():
        ticks += [100.0 * n, 100.0 * n + seconds]
    times = iter(ticks)
    assert _answers(_exam(tmp_path), model, clock=lambda: next(times)) == 0
    assert model.calls == 11
    out = capsys.readouterr().out.splitlines()
    assert out[2] == "Q03  dev       refusal   citations 0  model calls 0  0.0 s"
    assert out[-2] == (
        "Cold first answer 40.0 s. M4: median 10.5 s, slowest 15.6 s over 10 warm answers that"
        " called the model (10 of 14 questions; the cold one and 3 with no model call left out)."
        " Ollama 0.40.8."
    )


# --- grading sheet: about 100 characters of the answer, in whole words (Eo, 2026-10-26) ---

# Made up, shaped like Q01's answer: the 100th character falls inside "between", the amount
# follows, and the sentence ends with "per month." before 160 characters.
Q01_LIKE = (
    "Entry-level AI automation work in the Philippines is reported in the saved notes, and pay"
    " for it ranges between ₱40,000–₱60,000 per month. More text follows here."
)


def test_a_short_answer_is_shown_whole():
    assert evaluate.excerpt("  It is   thirty\nmetres.  ") == "It is thirty metres."
    exactly = "x" * 100
    assert evaluate.excerpt(exactly) == exactly


def test_q01_style_answer_runs_on_to_the_end_of_its_sentence():
    short = evaluate.excerpt(Q01_LIKE)
    assert short.endswith("₱40,000–₱60,000 per month.")
    assert "More text" not in short and not short.endswith("…")
    assert len(short) <= 160


def test_a_long_unbroken_word_is_finished_not_cut():
    words = "word " * 19 + "abc"  # 98 characters, so the amount is being written at 100
    text = words + " ₱40,000–₱60,000/month and then some more words without an end"
    short = evaluate.excerpt(text)
    assert short == words + " ₱40,000–₱60,000/month…"


def test_without_a_sentence_end_it_stops_after_a_whole_word_with_an_ellipsis():
    text = "ab " + " ".join(f"w{n:03d}" for n in range(60))  # no sentence end
    assert text[99] != " "  # the 100th character is inside a word
    short = evaluate.excerpt(text)
    assert short.endswith("…")
    body = short[:-1]
    assert text.startswith(body) and text[len(body)] == " "  # stopped at a word boundary
    assert 100 <= len(body) <= 104


def test_a_sentence_end_after_160_is_not_used():
    text = "word " * 19 + "abcde" + " filler" * 9 + " end. After."  # the "." is past 160
    assert text.index(".") > 160
    short = evaluate.excerpt(text)
    assert short == "word " * 19 + "abcde…"


def test_the_160_cap_holds_when_finishing_the_word_would_pass_it():
    long_word = "x" * 80  # starts before 100 and would end after 160
    text = "word " * 19 + long_word + " tail."
    short = evaluate.excerpt(text)
    assert short == ("word " * 19).rstrip() + "…"  # cut at the last space before 100
    assert len(short) <= 161


def test_one_word_longer_than_the_cap_is_the_only_cut_inside_a_word():
    assert evaluate.excerpt("y" * 300) == "y" * 100 + "…"


def test_the_sheet_uses_the_excerpt_and_still_escapes_pipes():
    answer = ask.Answer("answer", "A | B " + Q01_LIKE, None, (), (), 1)
    cited = ask.Cited(7, 1, "Quote.", "T", "s", None, None, SAVED)
    answer = ask.Answer("answer", answer.text, None, (cited,), (), 1)
    sheet = evaluate.grading_sheet(
        [(evaluate.Question(1, "dev", "Q?"), answer, 1.0)], date(2026, 10, 26)
    )
    assert "| Answer (about 100 characters, whole words) |" in sheet
    row = next(line for line in sheet.splitlines() if line.startswith("| 01 "))
    assert row.startswith("| 01 | dev | A \\| B Entry-level ")
    assert "per month. |" in row and "More text" not in row
