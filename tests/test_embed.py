import numpy as np
import pytest

from agila import embed
from agila.chunking import CACHE_DIR, Chunk, embedded_text
from agila.embed import (
    DIMENSIONS,
    QUERY_INSTRUCTION,
    USE_QUERY_INSTRUCTION,
    embed_chunks,
    embed_question,
)


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


# --- block h: the question embedding ---


class QuestionFake:
    """Records the question text it gets and returns the given vector."""

    def __init__(self, vector=None):
        self.seen = []
        self.vector = vector if vector is not None else np.eye(DIMENSIONS, dtype=np.float32)[0]

    def query_embed(self, query):
        self.seen.append(query)
        return iter([self.vector])


def test_question_gets_the_query_instruction_by_default():
    # Kept on the golden set dev half, block l (U10).
    assert USE_QUERY_INSTRUCTION is True
    fake = QuestionFake()
    vector = embed_question("  What is a URL?  ", embedder=fake)
    assert fake.seen == [QUERY_INSTRUCTION + "What is a URL?"]
    assert QUERY_INSTRUCTION == "Represent this sentence for searching relevant passages: "
    assert (vector.dtype, vector.shape) == (np.float32, (DIMENSIONS,))


def test_the_instruction_can_be_forced_off_or_on():
    fake = QuestionFake()
    embed_question("What is a URL?", with_instruction=False, embedder=fake)
    embed_question("What is a URL?", with_instruction=True, embedder=fake)
    assert fake.seen == ["What is a URL?", QUERY_INSTRUCTION + "What is a URL?"]


def test_the_default_follows_the_setting(monkeypatch):
    fake = QuestionFake()
    monkeypatch.setattr(embed, "USE_QUERY_INSTRUCTION", False)
    embed_question("What is a URL?", embedder=fake)
    assert fake.seen == ["What is a URL?"]


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_a_blank_question_is_refused(blank):
    fake = QuestionFake()
    with pytest.raises(ValueError, match="Type a question"):
        embed_question(blank, embedder=fake)
    assert fake.seen == []


@pytest.mark.parametrize(
    "bad",
    [np.zeros(DIMENSIONS, dtype=np.float32), np.full(DIMENSIONS, np.nan, dtype=np.float32)],
)
def test_a_zero_or_broken_vector_is_rejected(bad):
    with pytest.raises(ValueError, match="empty vector"):
        embed_question("What is a URL?", embedder=QuestionFake(bad))


def test_a_question_vector_of_the_wrong_size_is_rejected():
    with pytest.raises(ValueError, match="384 float32"):
        embed_question("What is a URL?", embedder=QuestionFake(np.ones(10, dtype=np.float32)))


@pytest.mark.skipif(not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed")
def test_a_question_is_embedded_exactly_like_a_passage_with_the_instruction_in_front():
    from agila.embed import default_embedder

    question = "How can I build a personal knowledge base with an LLM?"
    model = default_embedder()
    with_it = next(iter(model.passage_embed([QUERY_INSTRUCTION + question])))
    without = next(iter(model.passage_embed([question])))
    assert np.array_equal(embed_question(question), with_it)
    assert np.array_equal(embed_question(question, with_instruction=False), without)
    assert not np.array_equal(with_it, without)
