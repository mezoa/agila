"""Turn chunks into 384-number vectors with the local embedding model (FR6)."""

from collections.abc import Iterable
from functools import lru_cache
from typing import Protocol

import numpy as np

from agila.chunking import CACHE_DIR, MODEL_NAME, Chunk, embedded_text

DIMENSIONS = 384


class Embedder(Protocol):
    def passage_embed(self, texts: Iterable[str]) -> Iterable[np.ndarray]: ...


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
