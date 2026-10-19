"""Postgres connection and numbered SQL migrations."""

import os
import sys
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

ENV_VARS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name}")
    return value


def connect(dbname: str | None = None, register: bool = True) -> psycopg.Connection:
    """Open a connection from the POSTGRES_* variables; never logs the password.

    register=False is for migrate: the vector type may not exist yet.
    """
    settings = {name: _setting(name) for name in ENV_VARS}
    conn = psycopg.connect(
        host=settings["POSTGRES_HOST"],
        port=int(settings["POSTGRES_PORT"]),
        user=settings["POSTGRES_USER"],
        password=settings["POSTGRES_PASSWORD"],
        dbname=dbname or settings["POSTGRES_DB"],
    )
    if register:
        register_vector(conn)
    return conn


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply unapplied .sql files in name order, one transaction each. Returns versions applied."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def main(argv: list[str]) -> int:
    if argv != ["migrate"]:
        print("usage: python -m agila.db migrate")
        return 2
    try:
        with connect(register=False) as conn:
            applied = migrate(conn)
    except (RuntimeError, psycopg.Error) as exc:
        print(f"migrate failed: {exc}")
        return 1
    print("applied: " + ", ".join(applied) if applied else "nothing to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
