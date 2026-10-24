"""Prove a backup can be restored, into agila_restore_test only (block k, V88, V89).

    uv run python scripts/restore_test.py [DUMP]      (default: the newest dump in backups/)

The target is always the literal agila_restore_test; any other name is refused before anything
runs (`--target` exists only so the refusal can be seen). `-C/--create` is never used: it would
recreate the dump's own database name, agila (V89). The restored documents and chunks are
compared with the counts file `backup.py` wrote next to the dump (Eo, K4). After a pass the test
database is dropped; after a failure it is left for a look and its name is printed (Eo, K5).
"""

import argparse
import json
import sys
from pathlib import Path

from backup import (
    BACKUPS,
    CommandError,
    Runner,
    count_rows,
    counts_file,
    in_db,
    is_dump,
    run,
)

TARGET = "agila_restore_test"
REMOTE = f"/tmp/{TARGET}.dump"
KEPT = f"The database {TARGET} was left in place for a look."


def check_target(name: str) -> None:
    if name != TARGET:
        raise CommandError(f'Refusing to restore into "{name}": the test only uses {TARGET}.')


def newest_dump(backups: Path) -> Path:
    dumps = sorted(backups.glob("agila-*.dump"))  # the timestamp in the name sorts by time
    if not dumps:
        raise CommandError(f"No dump in {backups}. Run: uv run python scripts/backup.py")
    return dumps[-1]


def prepare(runner: Runner, dump: Path) -> dict:
    """Every check that needs no database change; returns the counts at backup time."""
    if not dump.is_file() or not is_dump(dump):
        raise CommandError(f"{dump.name} is not a pg_dump file.")
    try:
        expected = json.loads(counts_file(dump).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CommandError(f"{counts_file(dump).name} is missing or unreadable.") from None
    # The container's real database must not be the test name either (V89).
    runner(in_db(f'test "$POSTGRES_DB" != {TARGET}'), "target check")
    return expected


def restore(runner: Runner, dump: Path) -> dict:
    """Restore `dump` into TARGET and return its counts."""
    runner(["docker", "compose", "cp", str(dump), f"db:{REMOTE}"], "copy")
    try:
        runner(in_db(f'dropdb -U "$POSTGRES_USER" --if-exists {TARGET}'), "dropdb")
        runner(in_db(f'createdb -U "$POSTGRES_USER" {TARGET}'), "createdb")
        restore_cmd = f'pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d {TARGET}'
        runner(in_db(f"{restore_cmd} {REMOTE}"), "pg_restore")
        restored = count_rows(runner, TARGET)
    finally:
        runner(in_db(f"rm -f {REMOTE}"), "clean-up")
    return restored


def main(argv: list[str] | None = None, runner: Runner = run, backups: Path = BACKUPS) -> int:
    parser = argparse.ArgumentParser(description="Restore a backup into agila_restore_test.")
    parser.add_argument("dump", nargs="?", type=Path, help="default: the newest dump in backups/")
    parser.add_argument("--target", default=TARGET, help=f"only {TARGET} is accepted")
    args = parser.parse_args(argv)
    try:
        check_target(args.target)
        dump = args.dump or newest_dump(backups)
        expected = prepare(runner, dump)
    except CommandError as exc:
        print(f"Restore test refused: {exc}")
        return 1
    print(f"Restoring {dump.name} into {TARGET}.")
    try:
        restored = restore(runner, dump)
    except CommandError as exc:
        print(f"Restore test FAILED: {exc} {KEPT}")
        return 1
    for table in expected:
        same = "=" if expected[table] == restored.get(table) else "!="
        print(f"{table} {expected[table]} {same} {restored.get(table)}")
    if restored != expected:
        print(f"Restore test FAILED: the counts differ from the backup. {KEPT}")
        return 1
    try:
        runner(in_db(f'dropdb -U "$POSTGRES_USER" {TARGET}'), "dropdb")
    except CommandError as exc:
        print(f"Restore test passed, but dropping {TARGET} failed: {exc}")
        return 1
    print("Restore test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
