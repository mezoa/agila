import hashlib
from pathlib import Path

import numpy as np
import pytest

from agila import library
from agila.chunking import CACHE_DIR, default_counter, embedded_text
from agila.library import SaveError, save_markdown, save_text, save_url
from agila.web import FetchError

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed"),
]

FIXTURES = Path(__file__).parent / "fixtures"

THREE_HEADINGS = """# Notes

## Alpha
Alpha text about agila.

## Beta
Beta text about links.

## Gamma
Gamma text about answers.
"""


class FakeEmbedder:
    def passage_embed(self, texts):
        return (np.full(384, i, dtype=np.float32) for i, _ in enumerate(texts))


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_save_text_stores_document_and_chunks(conn):
    text = "Agila saves links.\n\nIt answers."
    saved = save_text(conn, "My note", "note-1", text, FakeEmbedder())
    doc = conn.execute(
        "SELECT title, source_label, source_type, status, visibility FROM documents WHERE id = %s",
        (saved.document_id,),
    ).fetchone()
    assert doc == ("My note", "note-1", "text", "active", "anywhere")
    assert saved.chunk_count == _count(conn, "chunks") >= 1


def test_save_text_needs_title_and_label(conn):
    with pytest.raises(SaveError, match="title and a source label"):
        save_text(conn, " ", "label", "text", FakeEmbedder())
    with pytest.raises(SaveError, match="title and a source label"):
        save_text(conn, "Title", "", "text", FakeEmbedder())
    assert _count(conn, "documents") == 0


def test_save_markdown_chunks_start_at_headings(conn, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(THREE_HEADINGS, encoding="utf-8")
    saved = save_markdown(conn, path, embedder=FakeEmbedder())
    headings = [
        r[0]
        for r in conn.execute(
            "SELECT heading FROM chunks WHERE document_id = %s ORDER BY position",
            (saved.document_id,),
        )
    ]
    assert {"Alpha", "Beta", "Gamma"} <= set(headings)
    assert saved.chunk_count >= 3
    texts = [r[0] for r in conn.execute("SELECT text FROM chunks")]
    assert any(t.startswith("Alpha text") for t in texts)  # heading is stored apart from the text


def test_markdown_defaults_are_first_h1_and_file_name(conn, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(THREE_HEADINGS, encoding="utf-8")
    saved = save_markdown(conn, path, embedder=FakeEmbedder())
    row = conn.execute(
        "SELECT title, source_label, source_type, identity_key FROM documents WHERE id = %s",
        (saved.document_id,),
    ).fetchone()
    assert row == ("Notes", "notes.md", "markdown", "markdown:notes.md")


def test_markdown_title_falls_back_to_file_stem_and_can_be_set(conn, tmp_path):
    plain = tmp_path / "plain.md"
    plain.write_text("## Only a second-level heading\nSome text here.", encoding="utf-8")
    first = save_markdown(conn, plain, embedder=FakeEmbedder())
    second = save_markdown(
        conn, plain, title="Given", source_label="other.md", embedder=FakeEmbedder()
    )
    titles = dict(conn.execute("SELECT id, title FROM documents").fetchall())
    assert titles[first.document_id] == "plain"
    assert titles[second.document_id] == "Given"


def test_markdown_missing_file_is_a_readable_error(conn, tmp_path):
    with pytest.raises(SaveError, match="File not found"):
        save_markdown(conn, tmp_path / "missing.md", embedder=FakeEmbedder())


def test_embedding_has_384_numbers_and_settings_names_the_model(conn):
    save_text(conn, "T", "L", "First paragraph.\n\nSecond paragraph.", FakeEmbedder())
    vectors = [r[0].to_numpy() for r in conn.execute("SELECT embedding FROM chunks")]
    assert vectors
    assert all(v.shape == (384,) and v.dtype == np.float32 for v in vectors)
    settings = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    assert settings["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert settings["embedding_dim"] == "384"


def test_long_chunks_embedded_text_is_within_512_tokens(conn):
    title = "A rather long title " * 6
    text = "## Heading\n" + ("Agila keeps notes and answers questions from them. " * 600)
    path_text = text.replace("## Heading\n", "")
    save_text(conn, title.strip(), "long", path_text, FakeEmbedder())
    count = default_counter()
    rows = conn.execute("SELECT heading, text FROM chunks ORDER BY position").fetchall()
    assert len(rows) > 1
    for heading, chunk_text in rows:
        tokens = count(embedded_text(title.strip(), heading or "", chunk_text))
        assert tokens <= 400  # the cap; the model limit is 512


def test_failure_inside_the_transaction_leaves_nothing(conn, monkeypatch):
    # Wrong-length vector for the 2nd chunk: the document row and the 1st chunk row are already
    # written when the database rejects it, so only a rollback leaves the tables empty.
    def bad_vectors(title, chunks, embedder=None):
        return [np.zeros(384 if i == 0 else 10, dtype=np.float32) for i in range(len(chunks))]

    monkeypatch.setattr(library, "embed_chunks", bad_vectors)
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 250 for i in range(4))
    with pytest.raises(SaveError, match="nothing was saved"):
        save_text(conn, "T", "L", text, FakeEmbedder())
    assert _count(conn, "documents") == 0
    assert _count(conn, "chunks") == 0


def test_identity_key_and_hash_are_stored(conn):
    text = "Line one.\r\nLine two."
    saved = save_text(conn, "T", "my-label", text, FakeEmbedder())
    key, content_hash = conn.execute(
        "SELECT identity_key, content_hash FROM documents WHERE id = %s", (saved.document_id,)
    ).fetchone()
    assert key == "text:my-label"
    assert content_hash == hashlib.sha256(b"Line one.\nLine two.").hexdigest()


@pytest.mark.parametrize("text", ["", "   \n\n  "])
def test_empty_input_is_refused_and_writes_nothing(conn, text):
    with pytest.raises(SaveError, match="Nothing to save"):
        save_text(conn, "T", "L", text, FakeEmbedder())
    assert _count(conn, "documents") == 0


def test_same_identity_twice_gives_already_saved_and_one_document(conn):
    save_text(conn, "T", "same", "First version.", FakeEmbedder())
    with pytest.raises(SaveError, match="Already saved: same"):
        save_text(conn, "T", "same", "Changed version.", FakeEmbedder())
    assert _count(conn, "documents") == 1
    assert _count(conn, "chunks") == 1


# --- save_url (block f part 1): the fetch is always a fake, no network ---


def _page(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    def __init__(self, html=None, error=None):
        self.html, self.error, self.calls = html, error, []

    def __call__(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.html


def test_save_url_stores_a_web_document_with_its_urls(conn):
    url = "HTTPS://Example.test/Post/1/?utm_source=x&id=7#top"
    fetcher = FakeFetcher(_page("article.html"))
    saved = save_url(conn, url, fetcher=fetcher, embedder=FakeEmbedder())
    row = conn.execute(
        "SELECT title, source_type, source_url, normalized_url, identity_key, source_label,"
        " status FROM documents WHERE id = %s",
        (saved.document_id,),
    ).fetchone()
    normalized = "https://example.test/Post/1?id=7"
    assert row == (
        "How Agila Saves a Page", "web", url, normalized, normalized, normalized, "active"
    )
    assert fetcher.calls == [url]  # downloaded as given, not the normalized form
    texts = [r[0] for r in conn.execute("SELECT text FROM chunks")]
    assert any("Agila is a small assistant" in t for t in texts)
    for menu_text in ("Blog", "Contact", "Privacy", "Copyright"):
        assert not any(menu_text in t for t in texts)
    assert saved.chunk_count == len(texts) >= 1


def test_save_url_title_argument_wins_and_url_is_the_last_fallback(conn):
    fetcher = FakeFetcher(_page("article.html"))
    given = save_url(conn, "https://a.test/x", title=" My title ", fetcher=fetcher,
                     embedder=FakeEmbedder())
    no_title = "<html><body><p>" + "This is a plain sentence with several words in it. " * 6
    untitled = save_url(conn, "https://b.test/y/", fetcher=FakeFetcher(no_title),
                        embedder=FakeEmbedder())
    titles = dict(conn.execute("SELECT id, title FROM documents").fetchall())
    assert titles[given.document_id] == "My title"
    assert titles[untitled.document_id] == "https://b.test/y"  # the normalized URL


@pytest.mark.parametrize(
    ("fixture", "message"),
    [("menus.html", "under 200 characters"), ("empty.html", "No readable text")],
)
def test_thin_pages_are_rejected_and_store_nothing(conn, fixture, message):
    with pytest.raises(SaveError, match=message):
        save_url(conn, "https://shop.test/", fetcher=FakeFetcher(_page(fixture)),
                 embedder=FakeEmbedder())
    assert _count(conn, "documents") == 0
    assert _count(conn, "chunks") == 0


BAD_URLS = ["htp://example.test/a", "example.test/a", "ftp://example.test/a", ""]


@pytest.mark.parametrize("url", BAD_URLS)
def test_a_typo_url_is_refused_before_any_download(conn, url):
    fetcher = FakeFetcher(_page("article.html"))
    with pytest.raises(SaveError):
        save_url(conn, url, fetcher=fetcher, embedder=FakeEmbedder())
    assert fetcher.calls == []
    assert _count(conn, "documents") == 0


def test_a_failed_download_stores_nothing_and_keeps_its_sentence(conn):
    fetcher = FakeFetcher(error=FetchError("The page answered with status 404."))
    with pytest.raises(SaveError, match="status 404"):
        save_url(conn, "https://example.test/gone", fetcher=fetcher, embedder=FakeEmbedder())
    assert _count(conn, "documents") == 0


def test_same_url_with_other_tracking_parameters_is_already_saved(conn):
    fetcher = FakeFetcher(_page("article.html"))
    save_url(conn, "https://example.test/post", fetcher=fetcher, embedder=FakeEmbedder())
    with pytest.raises(SaveError, match="Already saved: https://example.test/post"):
        save_url(
            conn,
            "HTTPS://Example.test/post/?utm_source=mail&fbclid=abc#comments",
            fetcher=fetcher,
            embedder=FakeEmbedder(),
        )
    assert _count(conn, "documents") == 1
