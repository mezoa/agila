"""Search the saved passages: up to 3 chunks of active documents, closest to a question (FR9, FR10).

Read-only and model-free: this module never imports `llm.py` or an HTTP client, and never writes
(only the ask flow of block j updates `last_asked_at`, FR35). The sentence "I couldn't find this
in your saved material" belongs to the ask flow (blocks i and j), not here.
"""

from dataclasses import dataclass
from datetime import datetime

import psycopg

from agila.embed import Embedder, embed_question

# Set on the golden set dev half, with the query prefix, 2026-10-26 (FR13, U31, decisions.md):
# 2 dev errors (answerable Q03 0.630 and Q05 0.621 refused), no unanswerable let through (highest
# 0.657). Was 0.70 (block h). Checked once on the held-out half in the full run (eval/report.md).
MIN_SIMILARITY = 0.68

# Cosine distance `<=>`; similarity = 1 - distance (V54). `c.id` keeps equal scores in a stable
# order (V55). Archived and superseded documents are never searched (FR9); `laptop_only` ones
# only when the caller may see them (FR41).
TOP_CHUNKS = (
    "SELECT c.id, c.text, c.heading, c.page, d.title, d.source_url, d.source_label, d.saved_at,"
    " c.embedding <=> %s AS distance"
    " FROM chunks c JOIN documents d ON d.id = c.document_id"
    " WHERE d.status = 'active' AND (d.visibility = 'anywhere' OR %s)"
    " ORDER BY distance, c.id LIMIT %s"
)


@dataclass(frozen=True)
class Passage:
    chunk_id: int
    text: str
    heading: str | None
    page: int | None
    title: str
    source: str  # the link for a web page, else the source label
    saved_at: datetime
    similarity: float


@dataclass(frozen=True)
class SearchResult:
    """`passages`: at most `limit`, all at or above `min_similarity`, best first; empty means
    nothing is close enough. `best_similarity`: the top score even when it is below the
    threshold; None for an empty library."""

    passages: list[Passage]
    best_similarity: float | None
    min_similarity: float


def search(
    conn: psycopg.Connection,
    question: str,
    *,
    min_similarity: float = MIN_SIMILARITY,
    limit: int = 3,
    embedder: Embedder | None = None,
    with_instruction: bool | None = None,
    include_private: bool = True,
) -> SearchResult:
    """FR9: the closest chunks of active documents; FR10: no model is called.

    `with_instruction` goes to `embed_question` (None = the app's setting). `include_private`
    False leaves `laptop_only` documents out entirely, also from `best_similarity` (FR41: Discord
    and n8n). Raises ValueError with one readable sentence for a blank question.
    """
    vector = embed_question(question, with_instruction, embedder)
    with conn.transaction():  # short and read-only, so `conn` stays idle afterwards
        rows = conn.execute(TOP_CHUNKS, (vector, include_private, limit)).fetchall()
    found = [
        Passage(chunk_id, text, heading, page, title, url or label or "", saved_at, 1.0 - distance)
        for chunk_id, text, heading, page, title, url, label, saved_at, distance in rows
    ]
    return SearchResult(
        [p for p in found if p.similarity >= min_similarity],
        found[0].similarity if found else None,
        min_similarity,
    )
