import psycopg
import pytest
from pgvector import Vector

from agila import db

TEST_DB = "agila_test"


def test_missing_variable_names_it_but_not_the_password(monkeypatch):
    for name in db.ENV_VARS:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret-value-123")
    monkeypatch.delenv("POSTGRES_HOST")
    with pytest.raises(RuntimeError) as err:
        db.connect()
    assert "POSTGRES_HOST" in str(err.value)
    assert "secret-value-123" not in str(err.value)


def _recreate_test_database():
    assert TEST_DB == "agila_test"  # never drop anything else
    with db.connect(dbname="postgres", register=False) as admin:
        admin.autocommit = True
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")


@pytest.fixture
def empty_db():
    """Name of a fresh, empty database; dropped afterwards. Never touches `agila`."""
    _recreate_test_database()
    yield TEST_DB
    with db.connect(dbname="postgres", register=False) as admin:
        admin.autocommit = True
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture
def conn(empty_db):
    with db.connect(dbname=empty_db, register=False) as plain:
        db.migrate(plain)
    with db.connect(dbname=empty_db) as migrated:
        yield migrated


def _insert_document(conn, identity_key="doc-1", status="active"):
    return conn.execute(
        "INSERT INTO documents (space_id, title, source_type, identity_key, content_hash, status)"
        " VALUES ((SELECT id FROM spaces LIMIT 1), 'T', 'text', %s, 'h', %s) RETURNING id",
        (identity_key, status),
    ).fetchone()[0]


@pytest.mark.db
def test_migrate_on_empty_database(empty_db):
    with db.connect(dbname=empty_db, register=False) as plain:
        assert db.migrate(plain) == ["0001_init.sql"]
        tables = {
            r[0]
            for r in plain.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        }
        assert {
            "spaces",
            "documents",
            "chunks",
            "query_log",
            "settings",
            "schema_migrations",
        } <= tables
        assert plain.execute("SELECT name, kind FROM spaces").fetchall() == [("default", "local")]
        settings = dict(plain.execute("SELECT key, value FROM settings").fetchall())
        assert settings == {"embedding_model": "BAAI/bge-small-en-v1.5", "embedding_dim": "384"}


@pytest.mark.db
def test_second_migrate_is_a_noop(empty_db):
    with db.connect(dbname=empty_db, register=False) as plain:
        db.migrate(plain)
        assert db.migrate(plain) == []
        assert plain.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1


@pytest.mark.db
def test_document_and_chunk_round_trip(conn):
    doc_id = _insert_document(conn)
    vector = [0.01 * i for i in range(384)]
    conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding) VALUES (%s, 0, 'hello', %s)",
        (doc_id, Vector(vector)),
    )
    (title,) = conn.execute("SELECT title FROM documents WHERE id = %s", (doc_id,)).fetchone()
    text, embedding = conn.execute(
        "SELECT text, embedding FROM chunks WHERE document_id = %s", (doc_id,)
    ).fetchone()
    assert (title, text) == ("T", "hello")
    assert len(embedding.to_list()) == 384


@pytest.mark.db
def test_same_vector_has_zero_distance(conn):
    doc_id = _insert_document(conn)
    vector = Vector([1.0] + [0.0] * 383)
    conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding) VALUES (%s, 0, 'a', %s)",
        (doc_id, vector),
    )
    (distance,) = conn.execute("SELECT embedding <=> %s FROM chunks", (vector,)).fetchone()
    assert distance == pytest.approx(0.0)


@pytest.mark.db
def test_deleting_a_document_removes_its_chunks(conn):
    doc_id = _insert_document(conn)
    conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding) VALUES (%s, 0, 'a', %s)",
        (doc_id, Vector([0.5] * 384)),
    )
    conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


@pytest.mark.db
def test_invalid_status_is_rejected(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_document(conn, status="bogus")


@pytest.mark.db
def test_timestamp_columns_are_timestamptz(conn):
    rows = conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'public' AND column_name IN"
        " ('saved_at', 'last_asked_at', 'created_at', 'asked_at', 'applied_at')"
    ).fetchall()
    assert len(rows) == 5
    assert {r[2] for r in rows} == {"timestamp with time zone"}
