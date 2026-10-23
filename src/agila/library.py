"""Save pasted text, Markdown or a web page as one document with chunks and vectors; list,
archive, unarchive and delete documents."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import errors

from agila.chunking import FRONT_MATTER, chunk_document
from agila.embed import Embedder, embed_chunks
from agila.urls import UrlError, normalize_url
from agila.web import WebError, extract_page, fetch_html

ACTIVE_IDENTITY_INDEX = "documents_active_identity"
MAX_WEB_CHUNKS = 200  # FR2 [assumed]: web pages needing more are refused (text and Markdown not)
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


@dataclass(frozen=True)
class Saved:
    """`outcome` is "saved", "unchanged" (identical content already active, nothing written) or
    "replaced" (the older active copies in `replaced_ids` are now superseded)."""

    document_id: int
    chunk_count: int
    title: str
    outcome: str = "saved"
    replaced_ids: tuple[int, ...] = ()
    warning: str | None = None


def describe(saved: Saved, name: str | None = None) -> str:
    """The one-sentence result of a save; a warning, if any, is printed on its own line."""
    if saved.outcome == "unchanged":
        return f"Already saved, unchanged: {saved.title} (document {saved.document_id})."
    sentence = f"Saved {name or saved.title}: {saved.chunk_count} chunks"
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
    replace: bool = False,
) -> Saved:
    """FR7 and FR8: compare with the active copies, chunk and embed, then write in ONE transaction.

    `conn` must be idle (no open transaction), so the blocks below really commit at their end;
    that is also why the first look-up runs in its own short transaction. The identity key
    defaults to source type + label (text, Markdown); web pages pass the normalized URL.
    Identical content already active: nothing is written or embedded. Changed content of a web
    page, or any save with `replace`: every active copy with the same identity is superseded
    BEFORE the insert (the web-only unique index would refuse the new row otherwise). A text or
    Markdown note with the label of another active note is kept beside it, with a warning.
    """
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
        chunks = chunk_document(title, text, is_markdown)
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
                    "UPDATE documents SET status = 'superseded' WHERE id = ANY(%s)",
                    (list(replaced_ids),),
                )
            document_id = conn.execute(
                "INSERT INTO documents (space_id, title, source_label, source_url,"
                " normalized_url, source_type, identity_key, content_hash, supersedes_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
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
                ),
            ).fetchone()[0]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, position, heading, text, embedding)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    [
                        (document_id, c.position, c.heading or None, c.text, vector)
                        for c, vector in zip(chunks, vectors, strict=True)
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
    if replaced_ids:
        return Saved(document_id, len(chunks), title, "replaced", replaced_ids)
    return Saved(document_id, len(chunks), title, warning=_label_warning(label, same))


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


def archive(conn: psycopg.Connection, document_id: int) -> str:
    """FR19: an active document becomes archived; its chunks stay, so unarchive brings it back
    exactly. Returns the title."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE documents SET status = 'archived' WHERE id = %s AND status = 'active'"
            " RETURNING title",
            (document_id,),
        ).fetchone()
        if row is None:
            status = _row(conn, document_id, "status")[0]
            raise LibraryError(
                f"Document {document_id} is {status}; only active documents can be archived."
            )
    return row[0]


def unarchive(conn: psycopg.Connection, document_id: int) -> str:
    """FR19: an archived document becomes active again. A web page is refused while a newer copy
    of its link is active (Eo, block g Q6). Returns the title."""
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
        conn.execute("UPDATE documents SET status = 'active' WHERE id = %s", (document_id,))
    return title


def document_info(conn: psycopg.Connection, document_id: int) -> DocumentInfo:
    """What a delete would remove (the dry run of `delete` without --yes)."""
    with conn.transaction():
        return _info(conn, document_id)


def delete_document(conn: psycopg.Connection, document_id: int) -> DocumentInfo:
    """FR20: delete one document by id; its chunks go with it (ON DELETE CASCADE) and a newer
    copy's `supersedes_id` becomes NULL (ON DELETE SET NULL). There is no undo."""
    with conn.transaction():
        info = _info(conn, document_id)
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    return info


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
