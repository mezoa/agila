"""The ask flow that the CLI and the API share: search, answer, then log it (FR35).

`retrieval.search` finds the passages and `ask.answer` writes the checked answer; this module adds
the one write a question makes: a `query_log` row (no question text, no answer text) and, for an
answered question only, `last_asked_at` on the documents of the CITED chunks (Eo, 7.J1). `/search`
and the evaluation never come through here, so they change neither.
"""

import time
from collections.abc import Callable
from types import ModuleType

import psycopg

from agila import llm
from agila.ask import Answer, Model, answer
from agila.embed import Embedder
from agila.retrieval import search

CHANNELS = ("cli", "web", "discord")
# Answer.kind -> query_log.status. `passages` and `busy` both show passages only (assumed, 7.J1).
STATUS = {"answer": "answered", "refusal": "refused", "passages": "fallback", "busy": "fallback"}


def ask_question(
    conn: psycopg.Connection,
    question: str,
    channel: str,
    *,
    model: Model | ModuleType = llm,
    embedder: Embedder | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Answer:
    """Search, answer, record. Raises ValueError with one sentence for a blank question (nothing
    is written then)."""
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel {channel!r}; use one of {', '.join(CHANNELS)}.")
    started = clock()
    result = answer(question, search(conn, question, embedder=embedder).passages, model=model)
    record(conn, result, channel, clock() - started)
    return result


def record(conn: psycopg.Connection, result: Answer, channel: str, seconds: float) -> None:
    """One transaction: the log row (retrieved chunk ids) and, when answered, `last_asked_at`."""
    with conn.transaction():
        conn.execute(
            "INSERT INTO query_log (channel, chunk_ids, status, seconds) VALUES (%s, %s, %s, %s)",
            (channel, [p.chunk_id for p in result.passages], STATUS[result.kind], seconds),
        )
        if result.kind == "answer":
            conn.execute(
                "UPDATE documents SET last_asked_at = now()"
                " WHERE id IN (SELECT document_id FROM chunks WHERE id = ANY(%s))",
                ([c.chunk_id for c in result.citations],),
            )
