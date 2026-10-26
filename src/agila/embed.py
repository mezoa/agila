"""Turn chunks into 384-number vectors with the local embedding model (FR6)."""

from collections.abc import Iterable
from functools import lru_cache
from typing import Protocol

import numpy as np

from agila.chunking import CACHE_DIR, MODEL_NAME, Chunk, embedded_text

DIMENSIONS = 384
# BGE's retrieval instruction for questions (V11). Passages never get it (V29, `embed_chunks`).
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
# ON for every question (CLI, API, evaluation): kept on the golden set dev half, 2026-10-26 (U10,
# decisions.md). Stored chunk vectors do not change, so nothing needs re-embedding.
USE_QUERY_INSTRUCTION = True


class Embedder(Protocol):
    def passage_embed(self, texts: Iterable[str]) -> Iterable[np.ndarray]: ...

    def query_embed(self, query: str) -> Iterable[np.ndarray]: ...


@lru_cache(maxsize=1)
def default_embedder() -> Embedder:
    """Load the embedding model once (cache in <repo>/.cache/fastembed)."""
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))


def embed_chunks(
    title: str, chunks: list[Chunk], embedder: Embedder | None = None
) -> list[np.ndarray]:
    """One float32 vector per chunk, in order. Passages get no instruction prefix (V29)."""
    if not chunks:
        return []
    texts = [embedded_text(title, chunk.heading, chunk.text) for chunk in chunks]
    vectors = list((embedder or default_embedder()).passage_embed(texts))
    if len(vectors) != len(texts):
        raise ValueError(f"Embedding gave {len(vectors)} vectors for {len(texts)} chunks")
    for vector in vectors:
        if vector.dtype != np.float32 or vector.shape != (DIMENSIONS,):
            raise ValueError(f"Embedding must be {DIMENSIONS} float32 numbers, got {vector.shape}")
    return vectors


def embed_question(
    text: str, with_instruction: bool | None = None, embedder: Embedder | None = None
) -> np.ndarray:
    """The one place a question becomes a vector (V56): QUERY_INSTRUCTION + the question.

    `with_instruction=None` follows USE_QUERY_INSTRUCTION; True or False forces it (the evaluation
    compares both).
    """
    if not text.strip():
        raise ValueError("Type a question to search for.")
    use = USE_QUERY_INSTRUCTION if with_instruction is None else with_instruction
    query = (QUERY_INSTRUCTION if use else "") + text.strip()
    vector = next(iter((embedder or default_embedder()).query_embed(query)))
    if vector.dtype != np.float32 or vector.shape != (DIMENSIONS,):
        raise ValueError(f"Embedding must be {DIMENSIONS} float32 numbers, got {vector.shape}")
    if not np.all(np.isfinite(vector)) or not np.any(vector):
        raise ValueError("The question gave an empty vector; try rewording it.")  # NaN distances
    return vector
