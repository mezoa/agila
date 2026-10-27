"""Save pasted text, Markdown, a web page or a text PDF as one document with chunks and vectors;
list, archive, unarchive and delete documents."""

import dataclasses
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import errors

from agila import export
from agila.chunking import FRONT_MATTER, Chunk, chunk_document
from agila.embed import Embedder, embed_chunks
from agila.pdf import PdfError, read_pdf
from agila.urls import UrlError, normalize_url
from agila.web import WebError, extract_page, fetch_html

ACTIVE_IDENTITY_INDEX = "documents_active_identity"
MAX_WEB_CHUNKS = 200  # FR2 [assumed]: web pages needing more are refused (text, Markdown, PDF not)
H1 = re.compile(r"^#[ \t]+(.*\S)[ \t]*$")


class SaveError(Exception):
    """A failure with one readable sentence; nothing was saved."""


class LibraryError(Exception):
    """A list, archive, unarchive or delete failure with one readable sentence; nothing changed."""


class NotFound(LibraryError):
    """No document has that id (the API answers 404)."""


@dataclass(frozen=True)
class Listed:
    document_id: int
    title: str
    saved_at: datetime
    status: str
    visibility: str


@dataclass(frozen=True)
class DocumentInfo:
    document_id: int
    title: str
    source_type: str
    saved_at: datetime
    chunk_count: int
    export_warning: str | None = None


@dataclass(frozen=True)
class Saved:
    """`outcome` is "saved", "unchanged" (identical content already active, nothing written) or
    "replaced" (the older active copies in `replaced_ids` are now superseded). `page_count` is
    set for a PDF only. `export_warning` is one sentence when the Obsidian note was not written
    (FR28: the save itself still stands)."""

    document_id: int
    chunk_count: int
    title: str
    outcome: str = "saved"
    replaced_ids: tuple[int, ...] = ()
    warning: str | None = None
    page_count: int | None = None
    export_warning: str | None = None


@dataclass(frozen=True)
class Changed:
    """An archive or unarchive: the title, and one sentence when the note was not updated."""

    title: str
    export_warning: str | None = None


def describe(saved: Saved, name: str | None = None) -> str:
    """The one-sentence result of a save; a warning, if any, is printed on its own line."""
    if saved.outcome == "unchanged":
        return f"Already saved, unchanged: {saved.title} (document {saved.document_id})."
    pages = f"{saved.page_count} pages, " if saved.page_count is not None else ""
    sentence = f"Saved {name or saved.title}: {pages}{saved.chunk_count} chunks"
    if saved.replaced_ids:
        sentence += f". It replaces {_documents(saved.replaced_ids)}, now superseded."
    return sentence


def save_text(
    conn: psycopg.Connection,
    title: str,
    source_label: str,
    text: str,
    embedder: Embedder | None = None,
    replace: bool = False,
) -> Saved:
    """FR1: save pasted text with a title and a source label."""
    if not title.strip() or not source_label.strip():
        raise SaveError("A title and a source label are both required.")
    return _save(
        conn, title.strip(), source_label.strip(), "text", text, False, embedder, replace=replace
    )


def save_markdown(
    conn: psycopg.Connection,
    path: Path,
    title: str | None = None,
    source_label: str | None = None,
    embedder: Embedder | None = None,
    replace: bool = False,
) -> Saved:
    """FR4: save a Markdown file. Title defaults to the first '# ' heading, else the file name
    without extension; the source label defaults to the file name with extension."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SaveError(f"File not found: {path}") from None
    except (OSError, UnicodeDecodeError):
        raise SaveError(f"Could not read {path} as UTF-8 text.") from None
    title = (title or "").strip() or _first_heading(text) or path.stem
    label = (source_label or "").strip() or path.name
    return _save(conn, title, label, "markdown", text, True, embedder, replace=replace)


def save_url(
    conn: psycopg.Connection,
    url: str,
    title: str | None = None,
    fetcher: Callable[[str], str] = fetch_html,
    embedder: Embedder | None = None,
    replace: bool = False,
) -> Saved:
    """FR2: check the link, download it, keep the main text, save it like any document.

    Title: `title` if given, else the page's own title, else the normalized URL. Nothing is stored
    when any step fails, including a page that needs more than MAX_WEB_CHUNKS chunks. The address
    block, redirects, size cap and content-type check live in `fetch_html`. `fetcher` is a
    parameter so tests can pass a fake.
    """
    try:
        normalized = normalize_url(url)  # also refuses anything that is not http or https
        page_title, text = extract_page(fetcher(url.strip()))
    except (UrlError, WebError) as exc:
        raise SaveError(str(exc)) from exc
    title = (title or "").strip() or page_title or normalized
    return _save(
        conn,
        title,
        normalized,
        "web",
        text,
        False,
        embedder,
        identity_key=normalized,
        source_url=url.strip(),
        normalized_url=normalized,
        max_chunks=MAX_WEB_CHUNKS,
        replace=replace,
    )


def save_pdf(
    conn: psycopg.Connection,
    path: Path,
    title: str | None = None,
    source_label: str | None = None,
    embedder: Embedder | None = None,
    replace: bool = False,
) -> Saved:
    """FR3: save a text PDF page by page; every chunk keeps its PDF page number (1-based).

    Title defaults to the file name without extension, the source label to the file name. The
    checks and the cleaning live in `pdf.read_pdf`; a refused file saves nothing. No chunk cap.
    The resolved path is stored so the original can be copied to the vault (FR28), also later
    by `export --retry`; an unchanged PDF saved before that column existed gets it now (Q3).
    """
    path = Path(path)
    try:
        pages = read_pdf(path)
    except PdfError as exc:
        raise SaveError(str(exc)) from exc
    title = (title or "").strip() or path.stem
    label = (source_label or "").strip() or path.name
    original = str(path.resolve())
    saved = _save(
        conn,
        title,
        label,
        "pdf",
        "",
        False,
        embedder,
        pages=pages,
        replace=replace,
        original_path=original,
    )
    if saved.outcome != "unchanged":
        return saved
    try:
        with conn.transaction():
            filled = conn.execute(
                "UPDATE documents SET original_path = %s, export_pending = true"
                " WHERE id = %s AND original_path IS NULL RETURNING id",
                (original, saved.document_id),
            ).fetchone()
    except psycopg.Error:
        return saved  # the save stands; the path is filled by a later save
    if filled is None:
        return saved
    warning = _after_change(conn, [saved.document_id], copy={saved.document_id})
    return dataclasses.replace(saved, export_warning=warning)


def _first_heading(markdown: str) -> str | None:
    in_fence = False
    for line in FRONT_MATTER.sub("", markdown.replace("\r\n", "\n"), count=1).split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        match = None if in_fence else H1.match(line)
        if match:
            return match.group(1)
    return None


def _save(
    conn: psycopg.Connection,
    title: str,
    label: str,
    source_type: str,
    text: str,
    is_markdown: bool,
    embedder: Embedder | None,
    *,
    identity_key: str | None = None,
    source_url: str | None = None,
    normalized_url: str | None = None,
    max_chunks: int | None = None,
    pages: list[str] | None = None,
    replace: bool = False,
    original_path: str | None = None,
) -> Saved:
    """FR7 and FR8: compare with the active copies, chunk and embed, then write in ONE transaction.

    `conn` must be idle (no open transaction), so the blocks below really commit at their end;
    that is also why the first look-up runs in its own short transaction. The identity key
    defaults to source type + label (text, Markdown); web pages pass the normalized URL.
    Identical content already active: nothing is written or embedded. Changed content of a web
    page, or any save with `replace`: every active copy with the same identity is superseded
    BEFORE the insert (the web-only unique index would refuse the new row otherwise). A text or
    Markdown note with the label of another active note is kept beside it, with a warning.
    A PDF passes its cleaned `pages` instead of `text`: the hash covers them joined with a form
    feed, each page is chunked on its own, and `page` and `page_count` are written.
    FR28: the new row and every superseded one are `export_pending` until their notes are
    written after the commit; a failed export only adds `export_warning`.
    """
    page_count = len(pages) if pages is not None else None
    if pages is not None:
        text = "\f".join(pages)
    text = text.replace("\r\n", "\n")
    identity_key = identity_key or f"{source_type}:{label}"
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    supersede = replace or source_type == "web"
    try:
        with conn.transaction():
            same = _active_copies(conn, identity_key)
            unchanged = _unchanged(conn, same, content_hash)
    except psycopg.Error as exc:
        raise SaveError(
            f"Saving {label} failed ({type(exc).__name__}); nothing was saved."
        ) from exc
    if unchanged:  # before the slow chunking and embedding
        return unchanged

    try:
        if pages is None:
            chunks = chunk_document(title, text, is_markdown)
            chunk_pages: list[int | None] = [None] * len(chunks)
        else:
            chunks, chunk_pages = _page_chunks(title, pages)
        if not chunks:
            raise SaveError(f"Nothing to save: no text found in {label}.")
        if max_chunks is not None and len(chunks) > max_chunks:  # before the slow embedding
            raise SaveError(f"The page is too long: it would need more than {max_chunks} chunks.")
        vectors = embed_chunks(title, chunks, embedder)
    except ValueError as exc:
        raise SaveError(f"Could not prepare {label}: {exc}") from exc

    try:
        with conn.transaction():
            same = _active_copies(conn, identity_key, lock=True)  # re-read under a lock
            unchanged = _unchanged(conn, same, content_hash)
            if unchanged:
                return unchanged
            replaced_ids = tuple(row[0] for row in same) if supersede else ()
            if replaced_ids:
                conn.execute(
                    "UPDATE documents SET status = 'superseded', export_pending = true"
                    " WHERE id = ANY(%s)",
                    (list(replaced_ids),),
                )
            document_id = conn.execute(
                "INSERT INTO documents (space_id, title, source_label, source_url,"
                " normalized_url, source_type, identity_key, content_hash, supersedes_id,"
                " page_count, original_path)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    _default_space(conn),
                    title,
                    label,
                    source_url,
                    normalized_url,
                    source_type,
                    identity_key,
                    content_hash,
                    replaced_ids[0] if replaced_ids else None,  # the newest old copy
                    page_count,
                    original_path,
                ),
            ).fetchone()[0]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, position, heading, page, text, embedding)"
                    " VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (document_id, c.position, c.heading or None, page, c.text, vector)
                        for c, page, vector in zip(chunks, chunk_pages, vectors, strict=True)
                    ],
                )
    except errors.UniqueViolation as exc:
        if exc.diag.constraint_name != ACTIVE_IDENTITY_INDEX:
            raise SaveError(f"Saving {label} failed; nothing was saved.") from exc
        if source_type != "web":  # only the old, wider index of 0001 refuses a second note
            raise SaveError(
                "The database needs an update: run uv run --env-file .env python -m agila.db"
                " migrate"
            ) from exc
        raise SaveError(
            f"Another save of {label} happened at the same time; nothing was saved. Try again."
        ) from exc
    except psycopg.Error as exc:
        raise SaveError(
            f"Saving {label} failed ({type(exc).__name__}); nothing was saved."
        ) from exc
    # only the new PDF is copied: an old copy keeps the bytes it was saved with
    exported = _after_change(conn, [document_id, *replaced_ids], copy={document_id})
    if replaced_ids:
        return Saved(
            document_id,
            len(chunks),
            title,
            "replaced",
            replaced_ids,
            page_count=page_count,
            export_warning=exported,
        )
    return Saved(
        document_id,
        len(chunks),
        title,
        warning=_label_warning(label, same),
        page_count=page_count,
        export_warning=exported,
    )


def _page_chunks(title: str, pages: list[str]) -> tuple[list[Chunk], list[int]]:
    """FR3: chunk each page on its own, so every chunk has exactly one PDF page (1-based);
    `position` runs across the whole document. A blank page gets no chunk."""
    chunks: list[Chunk] = []
    numbers: list[int] = []
    for number, page in enumerate(pages, 1):
        for c in chunk_document(title, page, False):
            chunks.append(Chunk(position=len(chunks), heading=c.heading, text=c.text))
            numbers.append(number)
    return chunks, numbers


def _default_space(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT id FROM spaces WHERE name = 'default'").fetchone()
    if row is None:
        raise SaveError("No default space; run the migrate command first.")
    return row[0]


def _active_copies(conn: psycopg.Connection, identity_key: str, lock: bool = False) -> list:
    """(id, title, content_hash) of the active documents with this identity, newest first."""
    return conn.execute(
        "SELECT id, title, content_hash FROM documents"
        " WHERE space_id = %s AND identity_key = %s AND status = 'active'"
        " ORDER BY saved_at DESC, id DESC" + (" FOR UPDATE" if lock else ""),
        (_default_space(conn), identity_key),
    ).fetchall()


def _unchanged(conn: psycopg.Connection, same: list, content_hash: str) -> Saved | None:
    for document_id, title, stored_hash in same:
        if stored_hash == content_hash:
            (count,) = conn.execute(
                "SELECT count(*) FROM chunks WHERE document_id = %s", (document_id,)
            ).fetchone()
            return Saved(document_id, count, title, "unchanged")
    return None


def _label_warning(label: str, same: list) -> str | None:
    if not same:
        return None
    named = " and ".join(f'document {document_id} "{title}"' for document_id, title, _ in same)
    return (
        f"Warning: a different note labelled {label} is already saved as {named}; both are kept."
        " Use --replace to supersede it."
        if len(same) == 1
        else f"Warning: different notes labelled {label} are already saved as {named}; all are"
        " kept. Use --replace to supersede them."
    )


def _documents(ids: tuple[int, ...]) -> str:
    if len(ids) == 1:
        return f"document {ids[0]}"
    return "documents " + ", ".join(str(i) for i in ids)


def list_documents(conn: psycopg.Connection) -> list[Listed]:
    """FR18: every document in the default space, whatever its status, newest first."""
    with conn.transaction():
        rows = conn.execute(
            "SELECT d.id, d.title, d.saved_at, d.status, d.visibility"
            " FROM documents d JOIN spaces s ON s.id = d.space_id WHERE s.name = 'default'"
            " ORDER BY d.saved_at DESC, d.id DESC"
        ).fetchall()
    return [Listed(*row) for row in rows]


def archive(conn: psycopg.Connection, document_id: int) -> Changed:
    """FR19: an active document becomes archived; its chunks stay, so unarchive brings it back
    exactly. FR28: its note's status is rewritten after the commit."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE documents SET status = 'archived', export_pending = true"
            " WHERE id = %s AND status = 'active' RETURNING title",
            (document_id,),
        ).fetchone()
        if row is None:
            status = _row(conn, document_id, "status")[0]
            raise LibraryError(
                f"Document {document_id} is {status}; only active documents can be archived."
            )
    return Changed(row[0], _after_change(conn, [document_id]))


def unarchive(conn: psycopg.Connection, document_id: int) -> Changed:
    """FR19: an archived document becomes active again. A web page is refused while a newer copy
    of its link is active (Eo, block g Q6). FR28: its note's status is rewritten after the
    commit."""
    with conn.transaction():
        title, status, source_type, space_id, identity_key = _row(
            conn, document_id, "title, status, source_type, space_id, identity_key", lock=True
        )
        if status != "archived":
            raise LibraryError(f"Document {document_id} is not archived.")
        if source_type == "web":
            newer = conn.execute(
                "SELECT id FROM documents WHERE space_id = %s AND identity_key = %s"
                " AND status = 'active' AND source_type = 'web'",
                (space_id, identity_key),
            ).fetchone()
            if newer:
                raise LibraryError(
                    f"A newer copy of this page is active (document {newer[0]});"
                    " archive or delete it first."
                )
        conn.execute(
            "UPDATE documents SET status = 'active', export_pending = true WHERE id = %s",
            (document_id,),
        )
    return Changed(title, _after_change(conn, [document_id]))


def document_info(conn: psycopg.Connection, document_id: int) -> DocumentInfo:
    """What a delete would remove (the dry run of `delete` without --yes)."""
    with conn.transaction():
        return _info(conn, document_id)


def delete_document(conn: psycopg.Connection, document_id: int) -> DocumentInfo:
    """FR20: delete one document by id; its chunks go with it (ON DELETE CASCADE) and a newer
    copy's `supersedes_id` becomes NULL (ON DELETE SET NULL). There is no undo. FR28: after the
    commit its note and PDF copy are deleted; a file that cannot be is named in one sentence."""
    with conn.transaction():
        info = _info(conn, document_id)
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    if not export.enabled():
        return info
    names = [export.note_name(info.title, document_id)]
    if info.source_type == "pdf":
        names.append(f"files/{export.pdf_name(info.title, document_id)}")
    left = export.delete_files(names)
    if not left:
        return info
    files = " and ".join(str(export.vault_dir() / name) for name in left)
    return dataclasses.replace(info, export_warning=f"Delete by hand: {files}.")


def retry_exports(conn: psycopg.Connection) -> tuple[int, int, list[str]]:
    """FR28 `export --retry`: write the note of every `export_pending` document (any status) and
    copy the original of each PDF that is not superseded. Returns (written, still pending,
    one sentence per document still pending)."""
    with conn.transaction():
        rows = conn.execute(
            "SELECT id, source_type, status FROM documents WHERE export_pending ORDER BY id"
        ).fetchall()
    sentences = []
    for document_id, source_type, status in rows:
        copy = {document_id} if source_type == "pdf" and status != "superseded" else set()
        warning = _after_change(conn, [document_id], copy=copy)
        if warning:
            sentences.append(warning)
    return len(rows) - len(sentences), len(sentences), sentences


def _after_change(
    conn: psycopg.Connection, document_ids: list[int], copy: set[int] | None = None
) -> str | None:
    """FR28, run AFTER a commit: write the note of each document from the database, copy the
    original of the PDFs in `copy`, then clear `export_pending` for those that fully worked.
    Never raises and never touches what was committed: a failure is one sentence, and the flag
    stays on for `export --retry`. Does nothing inside `export.off()`."""
    if not export.enabled() or not document_ids:
        return None
    try:
        docs, parts, originals = _notes(conn, document_ids)
    except Exception as exc:  # the save stands whatever goes wrong here
        return f"The Obsidian notes were not written ({type(exc).__name__}); run export --retry."
    done, problems = [], []
    for doc in docs:
        try:
            export.write_note(
                doc.document_id,
                export.note_name(doc.title, doc.document_id),
                export.render_note(doc, parts.get(doc.document_id, [])),
            )
            if doc.source_type == "pdf" and doc.document_id in (copy or set()):
                original = originals.get(doc.document_id)
                if original is None:
                    raise export.ExportError(
                        f"No original path is stored for {doc.title}; save it again with pdf PATH."
                    )
                name = export.pdf_name(doc.title, doc.document_id)
                export.copy_pdf(doc.document_id, Path(original), name)
            done.append(doc.document_id)
        except Exception as exc:  # any failure leaves the flag on
            cause = str(exc) if isinstance(exc, export.ExportError) else type(exc).__name__
            problems.append(
                f"The Obsidian note of document {doc.document_id} is pending: "
                f"{cause.rstrip('.')}; run export --retry."
            )
    if done:
        try:
            _clear_pending(conn, done)
        except Exception as exc:  # any failure leaves the flag on
            problems.append(
                f"The notes were written but not marked done ({type(exc).__name__});"
                " run export --retry."
            )
    return " ".join(problems) or None


def _notes(conn: psycopg.Connection, document_ids: list[int]):
    """The rows and chunks the notes are written from, read in one short transaction."""
    with conn.transaction():
        rows = conn.execute(
            "SELECT id, title, source_type, source_label, source_url, saved_at, status,"
            " page_count, original_path FROM documents WHERE id = ANY(%s) ORDER BY id",
            (list(document_ids),),
        ).fetchall()
        chunks = conn.execute(
            "SELECT document_id, text, heading, page FROM chunks WHERE document_id = ANY(%s)"
            " ORDER BY document_id, position",
            (list(document_ids),),
        ).fetchall()
    docs = [export.Doc(*row[:8]) for row in rows]
    originals = {row[0]: row[8] for row in rows}
    parts: dict[int, list[export.Part]] = {}
    for document_id, text, heading, page in chunks:
        parts.setdefault(document_id, []).append(export.Part(text, heading, page))
    return docs, parts, originals


def _clear_pending(conn: psycopg.Connection, document_ids: list[int]) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE documents SET export_pending = false WHERE id = ANY(%s)", (document_ids,)
        )


def _info(conn: psycopg.Connection, document_id: int) -> DocumentInfo:
    title, source_type, saved_at = _row(conn, document_id, "title, source_type, saved_at")
    (count,) = conn.execute(
        "SELECT count(*) FROM chunks WHERE document_id = %s", (document_id,)
    ).fetchone()
    return DocumentInfo(document_id, title, source_type, saved_at, count)


def _row(conn: psycopg.Connection, document_id: int, columns: str, lock: bool = False) -> tuple:
    """`columns` is always a constant from this module, never user input."""
    row = conn.execute(
        f"SELECT {columns} FROM documents WHERE id = %s" + (" FOR UPDATE" if lock else ""),
        (document_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"No document with id {document_id}.")
    return row
