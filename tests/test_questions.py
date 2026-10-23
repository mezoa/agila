import json
import math

import numpy as np
import pytest

from agila import llm, questions
from agila.ask import REFUSAL
from agila.questions import STATUS, ask_question

# Scripted vectors, as in test_retrieval.py: the question is e0; a chunk at similarity s is
# s*e0 + sqrt(1 - s^2)*e1.
Q = np.zeros(384, dtype=np.float32)
Q[0] = 1.0


def at(similarity):
    v = np.zeros(384, dtype=np.float32)
    v[0] = similarity
    v[1] = math.sqrt(1.0 - similarity**2)
    return v


class QuestionEmbedder:
    def query_embed(self, query):
        return iter([Q.copy()])


class ScriptedModel:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return llm.Reply(step, 1000)


def _reply(chunk_id, answerable=True):
    citations = [{"chunk_id": chunk_id, "sentence": 1}] if answerable else []
    text = "It says so." if answerable else ""
    return json.dumps({"answerable": answerable, "answer": text, "citations": citations})


def _library(conn):
    """Two documents: chunk `a` (0.90) in the first, chunk `b` (0.80) in the second."""
    ids = []
    for title, similarity in (("First", 0.90), ("Second", 0.80)):
        document = conn.execute(
            "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
            " content_hash) VALUES ((SELECT id FROM spaces LIMIT 1), %s, 'text', 'L', %s, 'h')"
            " RETURNING id",
            (title, f"text:{title}"),
        ).fetchone()[0]
        chunk = conn.execute(
            "INSERT INTO chunks (document_id, position, text, embedding)"
            " VALUES (%s, 0, 'One sentence here. Another one here.', %s) RETURNING id",
            (document, at(similarity)),
        ).fetchone()[0]
        ids.append((document, chunk))
    conn.commit()
    return ids


def _ask(conn, model, question="What does it say?", channel="cli"):
    return ask_question(conn, question, channel, model=model, embedder=QuestionEmbedder())


def _log(conn):
    return conn.execute(
        "SELECT channel, chunk_ids, status, seconds FROM query_log ORDER BY id"
    ).fetchall()


def _asked(conn):
    sql = "SELECT title, last_asked_at IS NOT NULL FROM documents ORDER BY id"
    return conn.execute(sql).fetchall()


def test_every_answer_kind_maps_to_an_allowed_status():
    assert set(STATUS) == {"answer", "refusal", "passages", "busy"}
    assert set(STATUS.values()) <= {"answered", "refused", "fallback"}
    assert (STATUS["passages"], STATUS["busy"]) == ("fallback", "fallback")


@pytest.mark.db
def test_an_answer_logs_the_retrieved_chunks_and_marks_only_the_cited_document(conn):
    (_, a), (_, b) = _library(conn)
    result = _ask(conn, ScriptedModel(_reply(a)))
    assert result.kind == "answer"
    ((channel, chunk_ids, status, seconds),) = _log(conn)
    assert (channel, chunk_ids, status) == ("cli", [a, b], "answered")
    assert seconds >= 0
    assert _asked(conn) == [("First", True), ("Second", False)]


@pytest.mark.db
def test_the_log_row_holds_no_question_or_answer_text(conn):
    (_, a), _ = _library(conn)
    _ask(conn, ScriptedModel(_reply(a)), question="A very particular question?")
    columns = [
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'query_log' ORDER BY ordinal_position"
        )
    ]
    assert columns == ["id", "asked_at", "channel", "chunk_ids", "status", "seconds"]
    assert "particular" not in str(conn.execute("SELECT * FROM query_log").fetchall())


@pytest.mark.db
def test_a_refusal_by_the_model_is_logged_and_marks_nothing(conn):
    (_, a), (_, b) = _library(conn)
    assert _ask(conn, ScriptedModel(_reply(a, answerable=False))).kind == "refusal"
    assert [row[:3] for row in _log(conn)] == [("cli", [a, b], "refused")]
    assert _asked(conn) == [("First", False), ("Second", False)]


@pytest.mark.db
def test_a_refusal_below_the_threshold_logs_no_chunks_and_calls_no_model(conn):
    document = conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
        " content_hash) VALUES ((SELECT id FROM spaces LIMIT 1), 'Far', 'text', 'L', 'text:Far',"
        " 'h') RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding) VALUES (%s, 0, 'Far.', %s)",
        (document, at(0.40)),
    )
    conn.commit()
    model = ScriptedModel()
    result = _ask(conn, model)
    assert (result.kind, result.text, model.calls) == ("refusal", REFUSAL, 0)
    assert [row[:3] for row in _log(conn)] == [("cli", [], "refused")]
    assert _asked(conn) == [("Far", False)]


@pytest.mark.db
def test_a_model_failure_is_logged_as_fallback_and_marks_nothing(conn):
    (_, a), (_, b) = _library(conn)
    result = _ask(conn, ScriptedModel(llm.ModelError(llm.NOT_RUNNING)))
    assert result.kind == "passages"
    assert [row[:3] for row in _log(conn)] == [("cli", [a, b], "fallback")]
    assert _asked(conn) == [("First", False), ("Second", False)]


@pytest.mark.db
def test_a_busy_answer_is_logged_as_fallback_and_marks_nothing(conn):
    (_, a), (_, b) = _library(conn)
    model = ScriptedModel()
    with llm.one_call_at_a_time():  # another question is being answered
        result = _ask(conn, model, channel="web")
    assert (result.kind, model.calls) == ("busy", 0)
    assert [row[:3] for row in _log(conn)] == [("web", [a, b], "fallback")]
    assert _asked(conn) == [("First", False), ("Second", False)]


@pytest.mark.db
def test_seconds_run_from_the_start_of_the_search_to_the_answer(conn):
    (_, a), _ = _library(conn)
    ticks = iter([10.0, 12.5])
    model, embedder = ScriptedModel(_reply(a)), QuestionEmbedder()
    ask_question(conn, "Q?", "cli", model=model, embedder=embedder, clock=lambda: next(ticks))
    assert _log(conn)[0][3] == 2.5


def test_a_blank_question_writes_nothing():
    class NoConnection:
        def __getattr__(self, name):
            raise AssertionError("the database must not be touched")

    with pytest.raises(ValueError, match="Type a question"):
        ask_question(
            NoConnection(), "   ", "cli", model=ScriptedModel(), embedder=QuestionEmbedder()
        )


def test_an_unknown_channel_is_refused_before_anything_runs():
    with pytest.raises(ValueError, match="Unknown channel"):
        questions.ask_question(None, "Q?", "email", model=ScriptedModel())
