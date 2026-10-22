"""Turn chunks into 384-number vectors with the local embedding model (FR6)."""

from collections.abc import Iterable
from functools import lru_cache
from typing import Protocol

import numpy as np

from agila.chunking import CACHE_DIR, MODEL_NAME, Chunk, embedded_text

DIMENSIONS = 384
# BGE's retrieval instruction for questions (V11). OFF by default; decided on the golden set (U10).
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


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
    text: str, with_instruction: bool = False, embedder: Embedder | None = None
) -> np.ndarray:
    """The one place a question becomes a vector: embedded like a passage, no prefix (V56).

    `with_instruction=True` prepends QUERY_INSTRUCTION; nothing turns it on before block l (U10).
    """
    if not text.strip():
        raise ValueError("Type a question to search for.")
    query = (QUERY_INSTRUCTION if with_instruction else "") + text.strip()
    vector = next(iter((embedder or default_embedder()).query_embed(query)))
    if vector.dtype != np.float32 or vector.shape != (DIMENSIONS,):
        raise ValueError(f"Embedding must be {DIMENSIONS} float32 numbers, got {vector.shape}")
    if not np.all(np.isfinite(vector)) or not np.any(vector):
        raise ValueError("The question gave an empty vector; try rewording it.")  # NaN distances
    return vector
