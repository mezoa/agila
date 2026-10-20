"""Temporary command line for the two saves (assumed, until the real CLI in block j).

    uv run --env-file .env python -m agila.ingest text --title T --label L [--file PATH]
    uv run --env-file .env python -m agila.ingest markdown PATH [--title T] [--label L]
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import psycopg

from agila import db
from agila.library import SaveError, save_markdown, save_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agila.ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    text = sub.add_parser("text", help="save pasted text (from --file or standard input)")
    text.add_argument("--title", required=True)
    text.add_argument("--label", required=True, help="source label")
    text.add_argument("--file", type=Path, help="read the text from this file, not stdin")
    markdown = sub.add_parser("markdown", help="save a Markdown file")
    markdown.add_argument("path", type=Path)
    markdown.add_argument("--title")
    markdown.add_argument("--label", help="source label (default: the file name)")
    return parser


def main(argv: list[str], connect: Callable[[], psycopg.Connection] = db.connect) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "markdown" and not args.path.is_file():
            raise SaveError(f"File not found: {args.path}")
        if args.command == "text":
            if args.file is not None and not args.file.is_file():
                raise SaveError(f"File not found: {args.file}")
            text = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
        with connect() as conn:
            if args.command == "text":
                saved = save_text(conn, args.title, args.label, text)
                name = args.title
            else:
                saved = save_markdown(conn, args.path, args.title, args.label)
                name = args.title or args.path.name
    except SaveError as exc:
        print(exc)
        return 1
    except RuntimeError as exc:  # a missing POSTGRES_* variable (db.connect never prints values)
        print(f"{exc}. Run with: uv run --env-file .env python -m agila.ingest ...")
        return 1
    except psycopg.OperationalError:
        print("Cannot reach the database. Start it with: docker compose up -d")
        return 1
    except (OSError, UnicodeDecodeError):
        print("Could not read the text as UTF-8. Check the file and try again.")
        return 1
    print(f"Saved {name}: {saved.chunk_count} chunks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
