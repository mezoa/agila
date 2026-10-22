import hashlib
from pathlib import Path

import numpy as np
import pytest

from agila import library
from agila.chunking import CACHE_DIR, Chunk, default_counter, embedded_text
from agila.library import SaveError, describe, save_markdown, save_text, save_url
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


def test_two_different_notes_with_the_same_label_are_both_kept_with_a_warning(conn):
    first = save_text(conn, "Old title", "same", "First version.", FakeEmbedder())
    second = save_text(conn, "T", "same", "Changed version.", FakeEmbedder())
    assert second.outcome == "saved"
    assert f'document {first.document_id} "Old title"' in second.warning
    assert "both are kept" in second.warning
    rows = conn.execute("SELECT status, supersedes_id FROM documents ORDER BY id").fetchall()
    assert rows == [("active", None), ("active", None)]
    assert _count(conn, "chunks") == 2


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
    [
        ("menus.html", "under 200 characters"),
        ("empty.html", "No readable text"),
        ("login_wall.html", "under 200 characters"),
    ],
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
    first = save_url(conn, "https://example.test/post", fetcher=fetcher, embedder=FakeEmbedder())
    embedder = CountingEmbedder()
    again = save_url(
        conn,
        "HTTPS://Example.test/post/?utm_source=mail&fbclid=abc#comments",
        fetcher=fetcher,
        embedder=embedder,
    )
    assert again.outcome == "unchanged"
    assert again.document_id == first.document_id
    assert describe(again).startswith("Already saved, unchanged")
    assert embedder.texts == 0
    assert _count(conn, "documents") == 1


# --- the 200-chunk cap (FR2, web pages only; block f part 2) ---


def _fake_chunks(count):
    chunks = [Chunk(i, "", f"Chunk number {i}.") for i in range(count)]
    return lambda title, text, is_markdown: chunks


class CountingEmbedder(FakeEmbedder):
    def __init__(self):
        self.texts = 0

    def passage_embed(self, texts):
        self.texts += len(texts)
        return super().passage_embed(texts)


def test_a_page_needing_more_than_200_chunks_is_refused_before_embedding(conn, monkeypatch):
    monkeypatch.setattr(library, "chunk_document", _fake_chunks(201))
    embedder = CountingEmbedder()
    with pytest.raises(SaveError, match="more than 200 chunks"):
        save_url(conn, "https://long.test/", fetcher=FakeFetcher(_page("article.html")),
                 embedder=embedder)
    assert embedder.texts == 0  # refused before the slow step
    assert _count(conn, "documents") == 0
    assert _count(conn, "chunks") == 0


def test_a_page_of_exactly_200_chunks_is_saved(conn, monkeypatch):
    monkeypatch.setattr(library, "chunk_document", _fake_chunks(200))
    saved = save_url(conn, "https://long.test/", fetcher=FakeFetcher(_page("article.html")),
                     embedder=FakeEmbedder())
    assert saved.chunk_count == 200
    assert _count(conn, "chunks") == 200


def test_the_chunk_cap_does_not_apply_to_pasted_text(conn, monkeypatch):
    monkeypatch.setattr(library, "chunk_document", _fake_chunks(201))
    saved = save_text(conn, "Long note", "long.txt", "words " * 10, embedder=FakeEmbedder())
    assert saved.chunk_count == 201


# --- block g: saving the same item again (FR7, FR8) ---


def _status(conn, document_id):
    return conn.execute(
        "SELECT status, supersedes_id FROM documents WHERE id = %s", (document_id,)
    ).fetchone()


def _changed_article():
    return _page("article.html").replace(
        "</article>",
        "<p>This paragraph was added later, so the content hash changes.</p></article>",
    )


def test_a_changed_page_supersedes_the_old_version(conn):
    url = "https://example.test/post"
    old = save_url(conn, url, fetcher=FakeFetcher(_page("article.html")), embedder=FakeEmbedder())
    new = save_url(conn, url, fetcher=FakeFetcher(_changed_article()), embedder=FakeEmbedder())
    assert new.outcome == "replaced"
    assert new.replaced_ids == (old.document_id,)
    assert _status(conn, old.document_id) == ("superseded", None)
    assert _status(conn, new.document_id) == ("active", old.document_id)
    active = conn.execute(
        "SELECT count(*) FROM documents WHERE identity_key = %s AND status = 'active'", (url,)
    ).fetchone()[0]
    assert active == 1
    old_chunks = conn.execute(
        "SELECT count(*) FROM chunks WHERE document_id = %s", (old.document_id,)
    ).fetchone()[0]
    assert old_chunks == old.chunk_count  # kept, only marked superseded
    assert describe(new) == (
        f"Saved {new.title}: {new.chunk_count} chunks."
        f" It replaces document {old.document_id}, now superseded."
    )


def test_replace_supersedes_the_note_with_the_same_label(conn):
    old = save_text(conn, "T", "notes", "First version.", FakeEmbedder())
    new = save_text(conn, "T", "notes", "Second version.", FakeEmbedder(), replace=True)
    assert (new.outcome, new.replaced_ids, new.warning) == ("replaced", (old.document_id,), None)
    assert _status(conn, old.document_id) == ("superseded", None)
    assert _status(conn, new.document_id) == ("active", old.document_id)


def test_an_identical_note_is_already_saved_unchanged(conn):
    first = save_text(conn, "T", "notes", "Same words.\n", FakeEmbedder())
    embedder = CountingEmbedder()
    again = save_text(conn, "T", "notes", "Same words.\r\n", embedder)  # line endings normalised
    assert (again.outcome, again.document_id, again.chunk_count) == (
        "unchanged", first.document_id, first.chunk_count
    )
    assert embedder.texts == 0
    assert _count(conn, "documents") == 1


def test_replace_with_identical_content_is_still_unchanged(conn):
    first = save_text(conn, "T", "notes", "Same words.", FakeEmbedder())
    again = save_text(conn, "T", "notes", "Same words.", FakeEmbedder(), replace=True)
    assert (again.outcome, again.document_id) == ("unchanged", first.document_id)
    assert _status(conn, first.document_id) == ("active", None)
    assert _count(conn, "documents") == 1


def test_replace_supersedes_every_active_note_with_that_label(conn):
    a = save_text(conn, "A", "notes", "Version A.", FakeEmbedder())
    b = save_text(conn, "B", "notes", "Version B.", FakeEmbedder())
    assert f'document {b.document_id} "B"' not in (b.warning or "")
    c = save_text(conn, "C", "notes", "Version C.", FakeEmbedder())
    assert f'document {b.document_id} "B" and document {a.document_id} "A"' in c.warning
    assert "all are kept" in c.warning
    d = save_text(conn, "D", "notes", "Version D.", FakeEmbedder(), replace=True)
    assert d.replaced_ids == (c.document_id, b.document_id, a.document_id)  # newest first
    assert _status(conn, d.document_id) == ("active", c.document_id)
    statuses = [_status(conn, x.document_id)[0] for x in (a, b, c)]
    assert statuses == ["superseded"] * 3


def test_a_failed_replace_leaves_the_old_version_active(conn, monkeypatch):
    old = save_text(conn, "T", "notes", "First version.", FakeEmbedder())

    def bad_vectors(title, chunks, embedder=None):  # 2nd chunk rejected inside the transaction
        return [np.zeros(384 if i == 0 else 10, dtype=np.float32) for i in range(len(chunks))]

    monkeypatch.setattr(library, "embed_chunks", bad_vectors)
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 250 for i in range(4))
    with pytest.raises(SaveError, match="nothing was saved"):
        save_text(conn, "T", "notes", text, FakeEmbedder(), replace=True)
    assert _status(conn, old.document_id) == ("active", None)
    assert _count(conn, "documents") == 1
    assert _count(conn, "chunks") == old.chunk_count


# --- block g: list, archive, unarchive, delete (FR18, FR19, FR20) ---


def _vectors(conn, document_id):
    return [
        (pos, text, emb.to_list())
        for pos, text, emb in conn.execute(
            "SELECT position, text, embedding FROM chunks WHERE document_id = %s"
            " ORDER BY position",
            (document_id,),
        )
    ]


def test_list_shows_title_date_status_and_visibility(conn):
    old = save_text(conn, "Old", "a", "First version.", FakeEmbedder())
    save_text(conn, "New", "a", "Second version.", FakeEmbedder(), replace=True)
    kept = save_text(conn, "Kept", "b", "Archived text.", FakeEmbedder())
    library.archive(conn, kept.document_id)
    rows = {d.title: d for d in library.list_documents(conn)}
    assert set(rows) == {"Old", "New", "Kept"}
    assert {d.title: d.status for d in rows.values()} == {
        "Old": "superseded", "New": "active", "Kept": "archived"
    }
    for d in rows.values():
        assert d.saved_at.tzinfo is not None
        assert d.visibility == "anywhere"
    assert rows["Old"].document_id == old.document_id


def test_archive_and_unarchive_round_trip(conn):
    saved = save_text(conn, "T", "L", "Some text to keep.", FakeEmbedder())
    before = _vectors(conn, saved.document_id)
    assert library.archive(conn, saved.document_id) == "T"
    assert _status(conn, saved.document_id)[0] == "archived"
    assert _vectors(conn, saved.document_id) == before
    assert library.unarchive(conn, saved.document_id) == "T"
    assert _status(conn, saved.document_id)[0] == "active"
    assert _vectors(conn, saved.document_id) == before


def test_archive_and_unarchive_refuse_the_wrong_status(conn):
    old = save_text(conn, "T", "L", "First version.", FakeEmbedder())
    new = save_text(conn, "T", "L", "Second version.", FakeEmbedder(), replace=True)
    with pytest.raises(library.LibraryError, match="^No document with id 999999.$"):
        library.archive(conn, 999999)
    with pytest.raises(library.LibraryError, match="^No document with id 999999.$"):
        library.unarchive(conn, 999999)
    with pytest.raises(library.LibraryError, match="is superseded; only active documents"):
        library.archive(conn, old.document_id)
    with pytest.raises(library.LibraryError, match=f"^Document {new.document_id} is not archived"):
        library.unarchive(conn, new.document_id)
    assert _status(conn, new.document_id)[0] == "active"


def test_unarchiving_a_page_with_a_newer_active_copy_is_refused(conn):
    url = "https://example.test/post"
    old = save_url(conn, url, fetcher=FakeFetcher(_page("article.html")), embedder=FakeEmbedder())
    library.archive(conn, old.document_id)
    # Q2: only active copies count, so the same link saved again is a new active copy
    new = save_url(conn, url, fetcher=FakeFetcher(_page("article.html")), embedder=FakeEmbedder())
    assert new.outcome == "saved" and new.document_id != old.document_id
    newer = f"newer copy .* active \\(document {new.document_id}\\)"
    with pytest.raises(library.LibraryError, match=newer):
        library.unarchive(conn, old.document_id)
    assert _status(conn, old.document_id)[0] == "archived"


def test_delete_removes_the_document_and_all_its_chunks(conn):
    doomed = save_text(conn, "Gone", "a", "Delete this text.", FakeEmbedder())
    other = save_text(conn, "Stays", "b", "Keep this text.", FakeEmbedder())
    info = library.delete_document(conn, doomed.document_id)
    assert (info.title, info.source_type, info.chunk_count) == ("Gone", "text", 1)
    for table, column in (("documents", "id"), ("chunks", "document_id")):
        left = conn.execute(
            f"SELECT count(*) FROM {table} WHERE {column} = %s", (doomed.document_id,)
        ).fetchone()[0]
        assert left == 0
    assert _vectors(conn, other.document_id) != []
    with pytest.raises(library.LibraryError, match="No document with id"):
        library.delete_document(conn, doomed.document_id)


def test_deleting_an_old_version_clears_the_link_from_the_new_one(conn):
    old = save_text(conn, "T", "L", "First version.", FakeEmbedder())
    new = save_text(conn, "T", "L", "Second version.", FakeEmbedder(), replace=True)
    library.delete_document(conn, old.document_id)
    assert _status(conn, new.document_id) == ("active", None)
