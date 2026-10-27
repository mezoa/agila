import psycopg
import pytest
from pgvector import Vector

from agila import db


def test_missing_variable_names_it_but_not_the_password(monkeypatch):
    for name in db.ENV_VARS:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret-value-123")
    monkeypatch.delenv("POSTGRES_HOST")
    with pytest.raises(RuntimeError) as err:
        db.connect()
    assert "POSTGRES_HOST" in str(err.value)
    assert "secret-value-123" not in str(err.value)


# --- block j: the /health database check (no database needed) ---


class _FakeConn:
    def __init__(self, seen):
        self.seen = seen

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.seen["sql"] = sql
        return self

    def fetchone(self):
        return (1,)


def test_the_database_check_runs_select_1_with_a_3_second_limit(monkeypatch):
    seen = {}

    def fake_connect(**kwargs):
        seen.update(kwargs)
        return _FakeConn(seen)

    monkeypatch.setattr(db, "connect", fake_connect)
    assert db.check_database() is None
    assert (seen["connect_timeout"], seen["register"], seen["sql"]) == (3, False, "SELECT 1")


def test_a_database_that_does_not_answer_gives_one_sentence(monkeypatch):
    def refused(**kwargs):
        raise psycopg.OperationalError("connection timeout expired")

    monkeypatch.setattr(db, "connect", refused)
    assert db.check_database() == db.DATABASE_DOWN
    assert len(db.DATABASE_DOWN.split()) <= 25


def test_a_missing_variable_in_the_check_is_named_without_a_value(monkeypatch):
    for name in db.ENV_VARS:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret-value-123")
    monkeypatch.delenv("POSTGRES_HOST")
    assert db.check_database() == (
        "Missing environment variable POSTGRES_HOST, so the database cannot be reached."
    )


def _insert_document(conn, identity_key="doc-1", status="active", source_type="text"):
    return conn.execute(
        "INSERT INTO documents (space_id, title, source_type, identity_key, content_hash, status)"
        " VALUES ((SELECT id FROM spaces LIMIT 1), 'T', %s, %s, 'h', %s) RETURNING id",
        (source_type, identity_key, status),
    ).fetchone()[0]


@pytest.mark.db
def test_migrate_on_empty_database(empty_db):
    with db.connect(dbname=empty_db, register=False) as plain:
        assert db.migrate(plain) == [
            "0001_init.sql",
            "0002_identity_index_web_only.sql",
            "0003_export.sql",
        ]
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
        assert plain.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 3


@pytest.mark.db
def test_documents_saved_before_0003_start_export_pending(empty_db, tmp_path):
    for name in ("0001_init.sql", "0002_identity_index_web_only.sql"):
        (tmp_path / name).write_bytes((db.MIGRATIONS_DIR / name).read_bytes())
    with db.connect(dbname=empty_db, register=False) as plain:
        db.migrate(plain, tmp_path)
        old_id = _insert_document(plain, "text:old")
        plain.commit()
        assert db.migrate(plain) == ["0003_export.sql"]
        new_id = _insert_document(plain, "text:new")
        rows = plain.execute(
            "SELECT id, export_pending, original_path FROM documents ORDER BY id"
        ).fetchall()
    assert rows == [(old_id, True, None), (new_id, True, None)]


@pytest.mark.db
def test_two_active_web_documents_with_one_identity_are_rejected(conn):
    _insert_document(conn, "https://example.test/a", source_type="web")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_document(conn, "https://example.test/a", source_type="web")


@pytest.mark.db
def test_two_active_text_documents_with_one_label_are_allowed(conn):
    _insert_document(conn, "text:notes")
    _insert_document(conn, "text:notes")
    assert conn.execute("SELECT count(*) FROM documents WHERE status = 'active'").fetchone()[0] == 2


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
