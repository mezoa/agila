import numpy as np
import pytest

from agila.chunking import CACHE_DIR, Chunk, embedded_text
from agila.embed import DIMENSIONS, embed_chunks


class FakeEmbedder:
    """Records the strings it gets and returns one float32 vector per string."""

    def __init__(self, vectors=None):
        self.seen = None
        self.vectors = vectors

    def passage_embed(self, texts):
        self.seen = list(texts)
        if self.vectors is not None:
            return self.vectors
        return (np.full(DIMENSIONS, i, dtype=np.float32) for i, _ in enumerate(self.seen))


CHUNKS = [Chunk(0, "Intro", "First text."), Chunk(1, "", "Second text.")]


def test_embedder_gets_title_heading_text_with_no_prefix():
    fake = FakeEmbedder()
    vectors = embed_chunks("My title", CHUNKS, fake)
    assert fake.seen == [
        embedded_text("My title", "Intro", "First text."),
        embedded_text("My title", "", "Second text."),
    ]
    assert fake.seen[0] == "My title\nIntro\nFirst text."
    assert not any("Represent this" in s for s in fake.seen)
    assert [v[0] for v in vectors] == [0.0, 1.0]  # order kept


def test_no_chunks_gives_no_vectors():
    assert embed_chunks("T", [], FakeEmbedder()) == []


def test_wrong_length_is_rejected():
    fake = FakeEmbedder([np.zeros(10, dtype=np.float32), np.zeros(DIMENSIONS, dtype=np.float32)])
    with pytest.raises(ValueError, match="384"):
        embed_chunks("T", CHUNKS, fake)


def test_wrong_dtype_is_rejected():
    fake = FakeEmbedder([np.zeros(DIMENSIONS, dtype=np.float64)] * 2)
    with pytest.raises(ValueError, match="float32"):
        embed_chunks("T", CHUNKS, fake)


def test_wrong_count_is_rejected():
    fake = FakeEmbedder([np.zeros(DIMENSIONS, dtype=np.float32)])
    with pytest.raises(ValueError, match="1 vectors for 2 chunks"):
        embed_chunks("T", CHUNKS, fake)


@pytest.mark.skipif(not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed")
def test_real_model_gives_384_float32_numbers():
    (vector,) = embed_chunks("T", [Chunk(0, "H", "Agila saves links.")])
    assert vector.dtype == np.float32
    assert vector.shape == (384,)
