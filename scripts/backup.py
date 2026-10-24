"""Back up the real database into backups/ (block k, V88, V90).

    uv run python scripts/backup.py

pg_dump runs inside the db container with the container's own POSTGRES_* variables and writes a
custom-format file there; `docker compose cp` copies it out. No PowerShell `>` (it corrupts the
dump, V90) and no `.env`: no value is read or printed. Next to each dump goes a counts file
(documents and chunks) that the restore test compares against (Eo, K4). Dumps are never deleted.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "backups"
TABLES = ("documents", "chunks")
REAL_DB = '"$POSTGRES_DB"'  # expanded by the container's shell, never by us
MAGIC = b"PGDMP"  # the first bytes of a custom-format dump (V88)

Runner = Callable[[list[str], str], str]


class CommandError(Exception):
    """One readable sentence; never a value from the environment."""


def run(args: list[str], step: str) -> str:
    """Run one docker command from the project folder and return its output.

    Its error output is not shown: it can hold the database user name.
    """
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    except OSError:
        raise CommandError("Docker is not available. Start Docker Desktop and try again.") from None
    if result.returncode != 0:
        raise CommandError(f"The {step} step failed (exit code {result.returncode}).")
    return result.stdout


def in_db(script: str) -> list[str]:
    """A shell command inside the db container, so $POSTGRES_* stay in there."""
    return ["docker", "compose", "exec", "-T", "db", "sh", "-c", script]


def count_rows(runner: Runner, database: str) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        psql = f'psql -U "$POSTGRES_USER" -d {database} -Atc "select count(*) from {table}"'
        out = runner(in_db(psql), f"count {table}")
        try:
            counts[table] = int(out.strip())
        except ValueError:
            raise CommandError(f"Counting {table} gave no number.") from None
    return counts


def counts_file(dump: Path) -> Path:
    return dump.with_name(dump.stem + ".counts.json")


def is_dump(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(len(MAGIC)) == MAGIC


def backup(runner: Runner = run, backups: Path = BACKUPS, now=datetime.now) -> Path:
    name = f"agila-{now():%Y%m%d-%H%M%S}.dump"
    remote = f"/tmp/{name}"
    local = backups / name
    before = count_rows(runner, REAL_DB)
    runner(in_db(f'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f {remote}'), "pg_dump")
    try:
        backups.mkdir(exist_ok=True)
        runner(["docker", "compose", "cp", f"db:{remote}", str(local)], "copy")
    finally:
        runner(in_db(f"rm -f {remote}"), "clean-up")
    if not local.exists() or not is_dump(local):
        raise CommandError(f"{local.name} is not a pg_dump file, so it cannot be restored.")
    if count_rows(runner, REAL_DB) != before:
        raise CommandError("The library changed during the backup. Run the backup again.")
    counts_file(local).write_text(json.dumps(before), encoding="utf-8")
    return local


def main(runner: Runner = run, backups: Path = BACKUPS, now=datetime.now) -> int:
    try:
        local = backup(runner, backups, now)
    except CommandError as exc:
        print(f"Backup failed: {exc}")
        return 1
    counts = json.loads(counts_file(local).read_text(encoding="utf-8"))
    shown = local.relative_to(ROOT) if local.is_relative_to(ROOT) else local
    print(
        f"Saved {shown} ({local.stat().st_size:,} bytes; "
        f"documents {counts['documents']}, chunks {counts['chunks']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
