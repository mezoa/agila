"""FR28: write each saved item as a note in the Obsidian vault, one way. This module writes,
renames and deletes its own files in `raw/agila/` and never reads, lists or opens anything there."""

import json
import os
import re
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_VAULT = Path(__file__).resolve().parents[2] / "raw" / "agila"
MAX_TITLE = 80  # characters of the title kept in a file name [assumed]
# Windows-reserved characters, control characters and Obsidian's link characters (V117, V118)
UNSAFE = re.compile(r'[<>:"/\\|?*#^\[\]%\x00-\x1f]')
EDGES = " .-"  # stripped from both ends: Windows drops a trailing dot or space (V119)
REPLACE_TRIES = 3  # a reader holding the note open makes os.replace fail (V120) [assumed]
REPLACE_WAIT = 0.2  # seconds between tries [assumed]
BLOCK = 1024 * 1024  # bytes read from a source PDF at a time

_enabled = True


class ExportError(Exception):
    """One sentence saying which file could not be written and why."""


@dataclass(frozen=True)
class Doc:
    """The document row a note is written from."""

    document_id: int
    title: str
    source_type: str
    source_label: str | None
    source_url: str | None
    saved_at: datetime
    status: str
    page_count: int | None = None


@dataclass(frozen=True)
class Part:
    """One chunk of the document, in `position` order."""

    text: str
    heading: str | None = None
    page: int | None = None


def vault_dir() -> Path:
    """The folder notes go to: `VAULT_PATH` if set, else `raw/agila` in the project folder."""
    return Path(os.environ.get("VAULT_PATH") or DEFAULT_VAULT)


def local_date(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d")  # the laptop's local date


def safe_title(title: str) -> str:
    """A file-name-safe form of the title, at most MAX_TITLE characters; never empty."""
    text = UNSAFE.sub("-", unicodedata.normalize("NFKC", title))
    text = re.sub(r"\s+", " ", text).strip(EDGES)
    return text[:MAX_TITLE].strip(EDGES) or "untitled"


def note_name(title: str, document_id: int) -> str:
    """`<safe title> (<id>).md`: the id keeps names unique, also when letter case differs."""
    return f"{safe_title(title)} ({document_id}).md"


def pdf_name(title: str, document_id: int) -> str:
    return f"{safe_title(title)} ({document_id}).pdf"


def render_note(doc: Doc, parts: list[Part]) -> str:
    """Properties (every text value as a JSON string, which YAML reads unchanged), then the
    cleaned text rebuilt from the chunks: `## heading` when it changes, `**PDF page N**` when a
    new page starts."""
    lines = [
        "---",
        f"title: {_quoted(doc.title)}",
        f"source: {_quoted(doc.source_url or doc.source_label or '')}",
        f"saved: {local_date(doc.saved_at)}",
        f"status: {doc.status}",
        "tags:",
        "  - agila",
        f"  - agila/{doc.source_type}",
        f"agila_id: {doc.document_id}",
        f"type: {doc.source_type}",
    ]
    if doc.page_count is not None:
        lines.append(f"pages: {doc.page_count}")
    lines.append("---")

    body: list[str] = []
    heading, page = None, None
    for part in parts:
        if part.page is not None and part.page != page:
            body.append(f"**PDF page {part.page}**")
        if part.heading and part.heading != heading:
            body.append(f"## {part.heading}")
        heading, page = part.heading, part.page
        body.append(part.text)
    return "\n".join(lines) + "\n\n" + "\n\n".join(body) + "\n"


def enabled() -> bool:
    return _enabled


@contextmanager
def off() -> Iterator[None]:
    """Turn the export off for one block of code (the evaluation library must not export)."""
    global _enabled
    before, _enabled = _enabled, False
    try:
        yield
    finally:
        _enabled = before


def write_note(document_id: int, name: str, text: str) -> None:
    """Write `.<id>.md.tmp` in the vault, then rename it over `name`: never a half-written note."""
    folder = vault_dir()
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".{document_id}.md.tmp"
    try:
        with open(temporary, "wb") as out:
            out.write(text.encode("utf-8"))
    except OSError as exc:
        raise ExportError(f"Could not write {name} ({type(exc).__name__}).") from exc
    _replace(temporary, folder / name)


def copy_pdf(document_id: int, source: Path, name: str) -> None:
    """Copy the original PDF to `files/<name>` through `.<id>.pdf.tmp`. Only `source`, which is
    outside the vault, is read; `shutil.copyfile` is not used because it stats the destination."""
    folder = vault_dir() / "files"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".{document_id}.pdf.tmp"
    try:
        with open(source, "rb") as original, open(temporary, "wb") as out:
            while block := original.read(BLOCK):
                out.write(block)
    except FileNotFoundError as exc:
        raise ExportError(
            f"The original PDF is no longer at {source}; save it again with pdf PATH."
        ) from exc
    except OSError as exc:
        raise ExportError(f"Could not copy {source} to files ({type(exc).__name__}).") from exc
    _replace(temporary, folder / name)


def delete_files(names: list[str]) -> list[str]:
    """Delete these vault files (a missing one is fine); returns the names that could not be."""
    folder = vault_dir()
    failed = []
    for name in names:
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            failed.append(name)
    return failed


def _replace(temporary: Path, target: Path) -> None:
    for attempt in range(1, REPLACE_TRIES + 1):
        try:
            os.replace(temporary, target)
            return
        except PermissionError as exc:
            if attempt == REPLACE_TRIES:
                raise ExportError(
                    f"Could not replace {target.name}; another program may have it open."
                ) from exc
            time.sleep(REPLACE_WAIT)
        except OSError as exc:
            raise ExportError(f"Could not replace {target.name} ({type(exc).__name__}).") from exc


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
