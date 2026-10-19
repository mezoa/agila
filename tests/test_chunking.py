import pytest

from agila.chunking import CACHE_DIR, CAP_TOKENS, chunk_document, default_counter, embedded_text


def fake_count(text: str) -> int:
    """Stand-in tokenizer: one token per whitespace-separated word."""
    return len(text.split())


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def run(title: str, text: str, is_markdown: bool = False):
    return chunk_document(title, text, is_markdown, count_tokens=fake_count)


def test_three_headings_give_three_chunks_starting_at_their_heading():
    text = "# One\nfirst body\n\n## Two\nsecond body\n\n# Three\nthird body\n"
    chunks = run("Notes", text, is_markdown=True)
    assert [c.heading for c in chunks] == ["One", "Two", "Three"]
    assert [c.text for c in chunks] == ["first body", "second body", "third body"]
    assert [c.position for c in chunks] == [0, 1, 2]


def test_text_before_the_first_heading_has_an_empty_heading():
    chunks = run("Notes", "intro line\n\n# One\nbody", is_markdown=True)
    assert [(c.heading, c.text) for c in chunks] == [("", "intro line"), ("One", "body")]


def test_no_headings_splits_by_paragraphs():
    paragraphs = [words(200, p) for p in "abc"]
    chunks = run("Notes", "\n\n".join(paragraphs))
    assert [c.text for c in chunks] == paragraphs
    assert {c.heading for c in chunks} == {""}


def test_short_paragraphs_are_packed_up_to_the_target():
    paragraphs = [words(99, p) for p in "abcd"]  # title adds 1: 3 x 99 + 1 fits 300
    chunks = run("Notes", "\n\n".join(paragraphs))
    assert [c.text for c in chunks] == ["\n\n".join(paragraphs[:3]), paragraphs[3]]


def test_heading_lines_are_text_when_not_markdown():
    chunks = run("Notes", "# not a heading\nbody", is_markdown=False)
    assert [(c.heading, c.text) for c in chunks] == [("", "# not a heading\nbody")]


def test_hash_lines_inside_code_fences_are_not_headings():
    text = "# Real\nbefore\n```\n# comment in code\n```\nafter"
    chunks = run("Notes", text, is_markdown=True)
    assert [c.heading for c in chunks] == ["Real"]
    assert "# comment in code" in chunks[0].text


def test_yaml_front_matter_is_stripped():
    text = "---\ntags: [a, b]\ndate: 2026-10-19\n---\n# One\nbody"
    chunks = run("Notes", text, is_markdown=True)
    assert [(c.heading, c.text) for c in chunks] == [("One", "body")]


def test_windows_line_endings_work():
    chunks = run("Notes", "# One\r\nfirst\r\n\r\n# Two\r\nsecond\r\n", is_markdown=True)
    assert [(c.heading, c.text) for c in chunks] == [("One", "first"), ("Two", "second")]


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
def test_empty_input_gives_no_chunks(text):
    assert run("Notes", text, is_markdown=True) == []
    assert run("Notes", text, is_markdown=False) == []


def test_front_matter_only_gives_no_chunks():
    assert run("Notes", "---\ntags: x\n---\n", is_markdown=True) == []


def test_ten_thousand_words_do_not_crash_and_stay_under_the_cap():
    paragraphs = [words(50, f"p{i}_") for i in range(200)]
    chunks = run("Notes", "\n\n".join(paragraphs))
    assert len(chunks) >= 10_000 // CAP_TOKENS
    assert all(fake_count(embedded_text("Notes", c.heading, c.text)) <= CAP_TOKENS for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_one_very_long_paragraph_without_breaks_stays_under_the_cap():
    text = words(10_000)
    chunks = run("Notes", text)
    assert len(chunks) > 1
    assert all(fake_count(embedded_text("Notes", c.heading, c.text)) <= CAP_TOKENS for c in chunks)
    assert " ".join(c.text for c in chunks) == text  # nothing lost or repeated


def test_one_huge_word_is_cut_by_characters():
    chunks = chunk_document("T", "x" * 5000, False, count_tokens=lambda s: len(s) // 10)
    assert len(chunks) > 1
    assert "".join(c.text for c in chunks) == "x" * 5000


def test_title_and_heading_count_toward_the_cap():
    title = words(60, "t")
    chunks = run(title, "# Head\n" + words(2000), is_markdown=True)
    assert all(fake_count(embedded_text(title, "Head", c.text)) <= CAP_TOKENS for c in chunks)
    assert max(fake_count(c.text) for c in chunks) < CAP_TOKENS - 60


def test_title_too_long_to_leave_room_is_an_error():
    with pytest.raises(ValueError):
        run(words(CAP_TOKENS), "some body text")


@pytest.mark.skipif(not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed")
def test_real_tokenizer_keeps_every_chunk_at_or_under_400():
    count = default_counter()
    title = "A fairly long document title for the counting test"
    long_paragraph = "The quick brown fox jumps over the lazy dog, again and again. " * 700
    text = "# First\n" + long_paragraph + "\n\n# Second\n" + words(3000) + "\n\n# Third\nshort."
    chunks = chunk_document(title, text, True, count_tokens=count)
    assert len(chunks) >= 3
    for c in chunks:
        assert count(embedded_text(title, c.heading, c.text)) <= 400
