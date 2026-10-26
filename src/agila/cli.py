"""The command line (FR25): save, ask, search, list, archive, unarchive, delete, evaluate.

    uv run --env-file .env python -m agila.cli text --title T --label L [--file PATH] [--replace]
    uv run --env-file .env python -m agila.cli markdown PATH [--title T] [--label L] [--replace]
    uv run --env-file .env python -m agila.cli url URL [--title T] [--replace]
    uv run --env-file .env python -m agila.cli pdf PATH [--title T] [--label L] [--replace]
    uv run --env-file .env python -m agila.cli list
    uv run --env-file .env python -m agila.cli archive ID
    uv run --env-file .env python -m agila.cli unarchive ID
    uv run --env-file .env python -m agila.cli delete ID [--yes]
    uv run --env-file .env python -m agila.cli search "QUESTION" [--min-similarity X]
    uv run --env-file .env python -m agila.cli ask "QUESTION"
    uv run --env-file .env python -m agila.cli evaluate ACTION   (see: evaluate --help)

It calls the library, search and ask functions directly, not the API, so it works with the API
stopped (Eo, 7.J1). `ask` needs Ollama and writes one `query_log` row with channel `cli` (FR35);
`search` writes nothing. `evaluate` hands everything after it to `evaluate.main`, which opens only
the database `agila_eval` and writes nothing to the real library (block l).
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import psycopg

from agila import db, evaluate
from agila.ask import format_answer
from agila.library import (
    LibraryError,
    SaveError,
    archive,
    delete_document,
    describe,
    document_info,
    list_documents,
    save_markdown,
    save_pdf,
    save_text,
    save_url,
    unarchive,
)
from agila.questions import ask_question
from agila.retrieval import MIN_SIMILARITY, search

MAX_ID = 2**63 - 1  # documents.id is a bigint
SHOWN_CHARACTERS = 300


def _similarity(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = float("nan")
    if not -1.0 <= value <= 1.0:  # also false for nan
        raise argparse.ArgumentTypeError(f"{text!r} is not a similarity between -1 and 1")
    return value


def _document_id(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= MAX_ID:
        raise argparse.ArgumentTypeError(f"{text!r} is not a document id (see the list command)")
    return int(text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agila.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    replace_help = "supersede the saved item with the same label or link"
    text = sub.add_parser("text", help="save pasted text (from --file or standard input)")
    text.add_argument("--title", required=True)
    text.add_argument("--label", required=True, help="source label")
    text.add_argument("--file", type=Path, help="read the text from this file, not stdin")
    text.add_argument("--replace", action="store_true", help=replace_help)
    markdown = sub.add_parser("markdown", help="save a Markdown file")
    markdown.add_argument("path", type=Path)
    markdown.add_argument("--title")
    markdown.add_argument("--label", help="source label (default: the file name)")
    markdown.add_argument("--replace", action="store_true", help=replace_help)
    url = sub.add_parser("url", help="save a web page (public http or https links only)")
    url.add_argument("url")
    url.add_argument("--title", help="title (default: the page title, else the link)")
    url.add_argument("--replace", action="store_true", help=replace_help)
    pdf = sub.add_parser("pdf", help="save a text PDF page by page (not a scan)")
    pdf.add_argument("path", type=Path)
    pdf.add_argument("--title", help="title (default: the file name without .pdf)")
    pdf.add_argument("--label", help="source label (default: the file name)")
    pdf.add_argument("--replace", action="store_true", help=replace_help)
    sub.add_parser("list", help="list documents with id, date, status, visibility and title")
    find = sub.add_parser("search", help="show up to 3 saved passages close to a question")
    find.add_argument("question")
    find.add_argument(
        "--min-similarity",
        type=_similarity,
        default=MIN_SIMILARITY,
        help=f"for this search only (default: {MIN_SIMILARITY})",
    )
    ask = sub.add_parser("ask", help="answer a question from the saved passages (needs Ollama)")
    ask.add_argument("question")
    sub.add_parser(
        "evaluate", help="the golden set in agila_eval (see: evaluate --help)", add_help=False
    )
    for name, what in (("archive", "archive"), ("unarchive", "un-archive")):
        command = sub.add_parser(name, help=f"{what} one document")
        command.add_argument("id", type=_document_id)
    delete = sub.add_parser("delete", help="delete one document and its chunks")
    delete.add_argument("id", type=_document_id)
    delete.add_argument("--yes", action="store_true", help="really delete (default: dry run)")
    return parser


def _date(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d")  # the laptop's local date


def _list(conn: psycopg.Connection) -> list[str]:
    docs = list_documents(conn)
    if not docs:
        return ["No documents saved yet."]
    return [
        f"{d.document_id:>4}  {_date(d.saved_at)}  {d.status:<10}  {d.visibility:<11}  {d.title}"
        for d in docs
    ]


def _delete(conn: psycopg.Connection, document_id: int, yes: bool) -> list[str]:
    if not yes:
        info = document_info(conn, document_id)
        return [
            f'Would delete document {info.document_id} "{info.title}" ({info.source_type},'
            f" saved {_date(info.saved_at)}, {info.chunk_count} chunks). Nothing deleted."
            " Run again with --yes to delete it."
        ]
    info = delete_document(conn, document_id)
    return [
        f'Deleted document {info.document_id} "{info.title}" and its {info.chunk_count} chunks.'
    ]


def _search(conn: psycopg.Connection, question: str, min_similarity: float) -> list[str]:
    result = search(conn, question, min_similarity=min_similarity)
    if result.best_similarity is None:
        return ["No documents saved yet."]
    if not result.passages:
        return [
            f"Nothing close enough: the best similarity was {result.best_similarity:.2f},"
            f" below the threshold {min_similarity:.2f}."
        ]
    lines = []
    for number, p in enumerate(result.passages, 1):
        saved = _date(p.saved_at)
        page = f", PDF page {p.page}" if p.page is not None else ""
        lines.append(
            f"{number}. {p.similarity:.2f}  {p.title}  ({p.source}{page}, saved {saved})"
        )
        if p.heading:
            lines.append(f"   Section: {p.heading}")
        text = " ".join(p.text.split())
        more = "..." if len(text) > SHOWN_CHARACTERS else ""
        lines.append("   " + text[:SHOWN_CHARACTERS] + more)
    return lines


def _ask(conn: psycopg.Connection, question: str) -> list[str]:
    """Search, the checked answer, and its `query_log` row (channel `cli`)."""
    return format_answer(ask_question(conn, question, "cli")).splitlines()


def _manage(conn: psycopg.Connection, args: argparse.Namespace) -> list[str]:
    if args.command == "ask":
        return _ask(conn, args.question)
    if args.command == "search":
        return _search(conn, args.question, args.min_similarity)
    if args.command == "list":
        return _list(conn)
    if args.command == "archive":
        return [f'Archived document {args.id} "{archive(conn, args.id)}".']
    if args.command == "unarchive":
        return [f'Unarchived document {args.id} "{unarchive(conn, args.id)}".']
    return _delete(conn, args.id, args.yes)


def main(argv: list[str], connect: Callable[[], psycopg.Connection] = db.connect) -> int:
    if argv[:1] == ["evaluate"]:  # its own actions and options; never opens `agila`
        return evaluate.main(argv[1:])
    args = _parser().parse_args(argv)
    try:
        if args.command in ("markdown", "pdf") and not args.path.is_file():
            raise SaveError(f"File not found: {args.path}")
        if args.command == "text":
            if args.file is not None and not args.file.is_file():
                raise SaveError(f"File not found: {args.file}")
            text = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
        with connect() as conn:
            if args.command in ("list", "archive", "unarchive", "delete", "search", "ask"):
                lines = _manage(conn, args)
            else:
                if args.command == "text":
                    saved = save_text(conn, args.title, args.label, text, replace=args.replace)
                    name = args.title
                elif args.command == "url":
                    saved = save_url(conn, args.url, args.title, replace=args.replace)
                    name = saved.title
                elif args.command == "pdf":
                    saved = save_pdf(conn, args.path, args.title, args.label, replace=args.replace)
                    name = saved.title
                else:
                    saved = save_markdown(
                        conn, args.path, args.title, args.label, replace=args.replace
                    )
                    name = args.title or args.path.name
                lines = [describe(saved, name)] + ([saved.warning] if saved.warning else [])
    except (SaveError, LibraryError) as exc:
        print(exc)
        return 1
    except RuntimeError as exc:  # a missing POSTGRES_* variable (db.connect never prints values)
        print(f"{exc}. Run with: uv run --env-file .env python -m agila.cli ...")
        return 1
    except psycopg.OperationalError:
        print("Cannot reach the database. Start it with: docker compose up -d")
        return 1
    except (OSError, UnicodeDecodeError):
        print("Could not read the text as UTF-8. Check the file and try again.")
        return 1
    except ValueError as exc:  # after UnicodeDecodeError, a subclass: a blank search question
        print(exc)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
