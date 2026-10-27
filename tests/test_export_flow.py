"""FR28 end to end on the test database: saves, status changes and deletes write the Obsidian
notes into a temporary vault, and nothing else in that vault is read or changed."""

import builtins
import hashlib
import io
import os
from pathlib import Path

import numpy as np
import pytest
from pdfs import text_pdf

from agila import export, library
from agila.chunking import CACHE_DIR
from agila.export import local_date, note_name, pdf_name
from agila.library import save_pdf, save_text, save_url

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed"),
]

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.test/post"
PAGES = [
    "Page one says the harbour opens at six in the morning every day of the week.",
    "",
    "Page three says the ferry leaves at noon and returns before the evening tide.",
]


class FakeEmbedder:
    def passage_embed(self, texts):
        return (np.full(384, i, dtype=np.float32) for i, _ in enumerate(texts))


def _fetcher(_url):
    return (FIXTURES / "article.html").read_text(encoding="utf-8")


def _pdf(tmp_path, name="harbour.pdf", pages=PAGES):
    path = tmp_path / "downloads" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text_pdf(pages))
    return path


def _row(conn, document_id, columns="export_pending"):
    return conn.execute(f"SELECT {columns} FROM documents WHERE id = %s", (document_id,)).fetchone()


def _note(vault, title, document_id):
    return (vault / note_name(title, document_id)).read_text(encoding="utf-8")


def _names(folder):
    if not folder.exists():
        return []
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


@pytest.fixture
def root(vault):
    """The whole vault (the project folder), with files Agila must never touch."""
    top = vault.parents[1]
    for name, text in [("docs/a.md", "# A\n"), (".obsidian/app.json", "{}"), ("notes/b.md", "b")]:
        (top / name).parent.mkdir(parents=True, exist_ok=True)
        (top / name).write_text(text, encoding="utf-8")
    return top


def _snapshot_outside(top, vault):
    return {
        p.relative_to(top).as_posix(): (p.stat().st_size, hashlib.sha256(p.read_bytes()).digest())
        for p in top.rglob("*")
        if p.is_file() and not p.is_relative_to(vault)
    }


# --- FR28 acceptance (1) to (5) ---


def test_a_saved_url_gives_a_note_with_its_properties_and_text(conn, vault):
    saved = save_url(conn, URL, fetcher=_fetcher, embedder=FakeEmbedder())
    assert saved.export_warning is None
    note = _note(vault, saved.title, saved.document_id)
    saved_at, pending = _row(conn, saved.document_id, "saved_at, export_pending")
    texts = [
        r[0]
        for r in conn.execute(
            "SELECT text FROM chunks WHERE document_id = %s ORDER BY position",
            (saved.document_id,),
        )
    ]
    head = (
        "---\n"
        f'title: "{saved.title}"\n'
        f'source: "{URL}"\n'
        f"saved: {local_date(saved_at)}\n"
        "status: active\n"
        "tags:\n"
        "  - agila\n"
        "  - agila/web\n"
        f"agila_id: {saved.document_id}\n"
        "type: web\n"
        "---\n\n"
    )
    assert note == head + "\n\n".join(texts) + "\n"
    assert pending is False


def test_a_saved_pdf_gives_a_note_with_pages_and_a_copy_of_the_original(conn, vault, tmp_path):
    source = _pdf(tmp_path)
    saved = save_pdf(conn, source, embedder=FakeEmbedder())
    note = _note(vault, "harbour", saved.document_id)
    assert "type: pdf\npages: 3\n---\n" in note
    assert "**PDF page 1**" in note and "**PDF page 3**" in note and "PDF page 2" not in note
    copy = vault / "files" / pdf_name("harbour", saved.document_id)
    assert copy.read_bytes() == source.read_bytes()
    assert _row(conn, saved.document_id, "original_path, export_pending") == (
        str(source.resolve()),
        False,
    )


def test_archive_unarchive_and_replace_rewrite_the_status(conn, vault, tmp_path):
    first = save_pdf(conn, _pdf(tmp_path), embedder=FakeEmbedder())
    result = library.archive(conn, first.document_id)
    assert result == library.Changed("harbour")
    assert "status: archived\n" in _note(vault, "harbour", first.document_id)
    library.unarchive(conn, first.document_id)
    assert "status: active\n" in _note(vault, "harbour", first.document_id)

    old_copy = vault / "files" / pdf_name("harbour", first.document_id)
    old_bytes = old_copy.read_bytes()
    revised = _pdf(tmp_path, pages=[PAGES[0], PAGES[2], PAGES[0] + " Revised."])
    second = save_pdf(conn, revised, embedder=FakeEmbedder(), replace=True)
    assert second.replaced_ids == (first.document_id,)
    assert "status: superseded\n" in _note(vault, "harbour", first.document_id)
    assert "status: active\n" in _note(vault, "harbour", second.document_id)
    assert old_copy.read_bytes() == old_bytes  # the old copy keeps the bytes it was saved with
    assert (vault / "files" / pdf_name("harbour", second.document_id)).exists()
    assert not _row(conn, first.document_id)[0] and not _row(conn, second.document_id)[0]


def test_delete_removes_the_note_and_the_pdf_copy_only(conn, vault, tmp_path):
    kept = save_text(conn, "Kept", "kept", "This note stays in the vault.", FakeEmbedder())
    gone = save_pdf(conn, _pdf(tmp_path), embedder=FakeEmbedder())
    info = library.delete_document(conn, gone.document_id)
    assert info.export_warning is None
    assert _names(vault) == [note_name("Kept", kept.document_id)]


def test_nothing_outside_raw_agila_changes(conn, vault, root, tmp_path):
    before = _snapshot_outside(root, vault)
    text = save_text(conn, "Note", "n", "Some text for the vault check.", FakeEmbedder())
    web = save_url(conn, URL, fetcher=_fetcher, embedder=FakeEmbedder())
    pdf = save_pdf(conn, _pdf(tmp_path), embedder=FakeEmbedder())
    library.archive(conn, text.document_id)
    library.unarchive(conn, text.document_id)
    replaced = save_text(conn, "Note", "n", "Other text.", FakeEmbedder(), replace=True)
    library.delete_document(conn, pdf.document_id)
    assert _snapshot_outside(root, vault) == before
    assert _names(vault) == sorted(
        [
            note_name("Note", text.document_id),
            note_name(web.title, web.document_id),
            note_name("Note", replaced.document_id),
        ]
    )


# --- (6) the export never reads the vault (decision 9) ---


def test_the_export_never_reads_or_lists_anything_in_the_vault(
    conn, vault, root, tmp_path, monkeypatch
):
    source = _pdf(tmp_path)
    seen = []

    def spy(name, real):
        def wrapper(*args, **kwargs):
            seen.append((name, args[0] if args else None, args[1] if len(args) > 1 else None))
            return real(*args, **kwargs)

        return wrapper

    with monkeypatch.context() as patch:
        for owner, name in [
            (builtins, "open"),
            (io, "open"),
            (os, "listdir"),
            (os, "scandir"),
            (os, "stat"),
            (Path, "iterdir"),
            (Path, "glob"),
        ]:
            patch.setattr(owner, name, spy(name, getattr(owner, name)))

        text = save_text(conn, "Note", "n", "Some text for the read check.", FakeEmbedder())
        pdf = save_pdf(conn, source, embedder=FakeEmbedder())
        library.archive(conn, text.document_id)
        library.unarchive(conn, text.document_id)
        save_text(conn, "Note", "n", "Other text.", FakeEmbedder(), replace=True)
        library.delete_document(conn, pdf.document_id)
        library.retry_exports(conn)

    allowed_stats = {vault, vault / "files"}
    inside = []
    for name, target, mode in seen:
        if target is None or isinstance(target, int):
            continue
        path = Path(os.fspath(target)).resolve()
        if not path.is_relative_to(root.resolve()):
            continue
        if name == "open" and mode == "wb":
            continue
        if name == "stat" and path in {p.resolve() for p in allowed_stats}:
            continue
        inside.append((name, path, mode))
    assert inside == []
    assert any(name == "open" and Path(t) == source and m == "rb" for name, t, m in seen)


# --- (7) to (11) failures, retry, unchanged saves, export off ---


def test_a_failed_note_keeps_the_save_and_retry_writes_it(conn, vault, monkeypatch):
    def broken(*_args):
        raise export.ExportError("Could not write Note (1).md (PermissionError).")

    with monkeypatch.context() as patch:
        patch.setattr(export, "write_note", broken)
        saved = save_text(conn, "Note", "n", "The save must stand.", FakeEmbedder())
        assert saved.outcome == "saved" and saved.chunk_count >= 1
        assert saved.export_warning == (
            f"The Obsidian note of document {saved.document_id} is pending: Could not write"
            " Note (1).md (PermissionError); run export --retry."
        )
        assert len(saved.export_warning.split()) <= 25
        assert _row(conn, saved.document_id)[0] is True
        archived = library.archive(conn, saved.document_id)
        assert archived.export_warning is not None
        assert _row(conn, saved.document_id, "status")[0] == "archived"  # the change stands

    assert export.vault_dir() == vault  # the temporary vault is still in place
    assert library.retry_exports(conn) == (1, 0, [])
    assert "status: archived\n" in _note(vault, "Note", saved.document_id)
    assert _row(conn, saved.document_id)[0] is False


def test_a_failing_flag_update_still_returns_the_save(conn, vault, monkeypatch):
    def broken(*_args):
        raise RuntimeError("database gone")

    monkeypatch.setattr(library, "_clear_pending", broken)
    saved = save_text(conn, "Note", "n", "The save must stand.", FakeEmbedder())
    assert saved.outcome == "saved"
    assert saved.export_warning == (
        "The notes were written but not marked done (RuntimeError); run export --retry."
    )
    assert _row(conn, saved.document_id)[0] is True
    assert (vault / note_name("Note", saved.document_id)).exists()


def test_retry_keeps_a_pdf_pending_while_its_original_is_missing(conn, vault, tmp_path):
    source = _pdf(tmp_path)
    saved = save_pdf(conn, source, embedder=FakeEmbedder())
    conn.execute("UPDATE documents SET export_pending = true WHERE id = %s", (saved.document_id,))
    conn.commit()
    source.unlink()
    written, pending, sentences = library.retry_exports(conn)
    assert (written, pending) == (0, 1)
    assert sentences == [
        f"The Obsidian note of document {saved.document_id} is pending: The original PDF is no"
        f" longer at {source.resolve()}; save it again with pdf PATH; run export --retry."
    ]
    assert "status: active\n" in _note(vault, "harbour", saved.document_id)
    assert _row(conn, saved.document_id)[0] is True


def test_an_unchanged_pdf_without_a_stored_path_gets_it_and_its_copy(conn, vault, tmp_path):
    source = _pdf(tmp_path)
    saved = save_pdf(conn, source, embedder=FakeEmbedder())
    copy = vault / "files" / pdf_name("harbour", saved.document_id)
    copy.unlink()
    conn.execute(  # as a PDF saved in block m, before migration 0003
        "UPDATE documents SET original_path = NULL, export_pending = true WHERE id = %s",
        (saved.document_id,),
    )
    conn.commit()
    assert library.retry_exports(conn)[:2] == (0, 1)
    again = save_pdf(conn, source, embedder=FakeEmbedder())
    assert again.outcome == "unchanged" and again.export_warning is None
    assert copy.read_bytes() == source.read_bytes()
    assert _row(conn, saved.document_id, "original_path, export_pending") == (
        str(source.resolve()),
        False,
    )


def test_an_unchanged_save_writes_nothing(conn, monkeypatch):
    save_text(conn, "Note", "n", "Same words.", FakeEmbedder())
    writes = []
    monkeypatch.setattr(export, "write_note", lambda *args: writes.append(args))
    again = save_text(conn, "Note", "n", "Same words.", FakeEmbedder())
    assert again.outcome == "unchanged" and writes == []


def test_inside_off_nothing_is_written_and_the_flag_stays(conn, vault):
    with export.off():
        saved = save_text(conn, "Note", "n", "Not exported.", FakeEmbedder())
        info = library.delete_document(
            conn, save_text(conn, "Other", "o", "Gone.", FakeEmbedder()).document_id
        )
    assert info.export_warning is None
    assert not vault.exists()
    assert _row(conn, saved.document_id)[0] is True


def test_a_note_that_cannot_be_deleted_is_named_in_one_sentence(conn, vault, monkeypatch):
    saved = save_text(conn, "Note", "n", "Locked by another program.", FakeEmbedder())
    monkeypatch.setattr(export, "delete_files", lambda names: names[:1])
    info = library.delete_document(conn, saved.document_id)
    name = note_name("Note", saved.document_id)
    assert info.export_warning == f"Delete by hand: {vault / name}."
    assert _row(conn, saved.document_id) is None  # the delete itself stands
