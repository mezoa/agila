"""Save pasted text, Markdown or a web page as one document with chunks and vectors."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Saved:
    document_id: int
    chunk_count: int
    title: str


def save_text(
    conn: psycopg.Connection,
    title: str,
    source_label: str,
    text: str,
    embedder: Embedder | None = None,
) -> Saved:
    """FR1: save pasted text with a title and a source label."""
    if not title.strip() or not source_label.strip():
        raise SaveError("A title and a source label are both required.")
    return _save(conn, title.strip(), source_label.strip(), "text", text, False, embedder)


def save_markdown(
    conn: psycopg.Connection,
    path: Path,
    title: str | None = None,
    source_label: str | None = None,
    embedder: Embedder | None = None,
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
    return _save(conn, title, label, "markdown", text, True, embedder)


def save_url(
    conn: psycopg.Connection,
    url: str,
    title: str | None = None,
    fetcher: Callable[[str], str] = fetch_html,
    embedder: Embedder | None = None,
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
) -> Saved:
    """Chunk and embed first (no database yet), then write everything in ONE transaction.

    `conn` must be idle (no open transaction), so the block below really commits at its end.
    The identity key defaults to source type + label (text, Markdown); web pages pass the
    normalized URL (PRD FR7).
    """
    text = text.replace("\r\n", "\n")
    try:
        chunks = chunk_document(title, text, is_markdown)
        if not chunks:
            raise SaveError(f"Nothing to save: no text found in {label}.")
        if max_chunks is not None and len(chunks) > max_chunks:  # before the slow embedding
            raise SaveError(f"The page is too long: it would need more than {max_chunks} chunks.")
        vectors = embed_chunks(title, chunks, embedder)
    except ValueError as exc:
        raise SaveError(f"Could not prepare {label}: {exc}") from exc

    identity_key = identity_key or f"{source_type}:{label}"
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    try:
        with conn.transaction():
            row = conn.execute("SELECT id FROM spaces WHERE name = 'default'").fetchone()
            if row is None:
                raise SaveError("No default space; run the migrate command first.")
            document_id = conn.execute(
                "INSERT INTO documents (space_id, title, source_label, source_url,"
                " normalized_url, source_type, identity_key, content_hash)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    row[0],
                    title,
                    label,
                    source_url,
                    normalized_url,
                    source_type,
                    identity_key,
                    content_hash,
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
        raise SaveError(
            f"Already saved: {label}. Replacing a saved item comes later (block g)."
        ) from exc
    except psycopg.Error as exc:
        raise SaveError(
            f"Saving {label} failed ({type(exc).__name__}); nothing was saved."
        ) from exc
    return Saved(document_id, len(chunks), title)
