import inspect
import json
import threading
import time
from datetime import UTC, datetime

import numpy as np
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from agila import api, db, llm, questions
from agila.retrieval import Passage, SearchResult

KEY = "test-key-not-a-secret"
GOOD = {"X-API-Key": KEY}
SAVED = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
TEXT = "Short passage text. A second one."
PASSAGE = Passage(11, TEXT, None, None, "llm-wiki", "https://example.test", SAVED, 0.8)
ANSWER = json.dumps(
    {"answerable": True, "answer": "It says so.", "citations": [{"chunk_id": 11, "sentence": 1}]}
)


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return llm.Reply(self.replies.pop(0), 1000)


def _no_warm_up():
    pass


@pytest.fixture
def no_database(monkeypatch):
    """The ask flow without Postgres: one scripted passage, and log rows kept in a list."""
    rows = []

    def one_passage(conn, question, embedder=None):
        return SearchResult([PASSAGE], 0.8, 0.7)

    def keep(conn, result, channel, seconds):
        rows.append((result.kind, channel))

    monkeypatch.setattr(questions, "search", one_passage)
    monkeypatch.setattr(questions, "record", keep)
    return rows


def _app(model=None, **kwargs):
    app = api.create_app(KEY, warm_up=_no_warm_up, model=model or ScriptedModel(), **kwargs)
    app.dependency_overrides[api.connection] = lambda: None
    return app


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(db, "check_database", lambda: None)
    monkeypatch.setattr(llm, "check_ollama", lambda: None)


# --- the key (decision 1) ---


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": ""}, {"X-API-Key": "wrong"}, {"X-API-Key": KEY + "x"}],
    ids=["missing", "empty", "wrong", "longer"],
)
def test_a_missing_empty_or_wrong_key_gets_one_401_sentence(headers):
    response = TestClient(_app()).get("/documents", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing or wrong API key."}
    assert response.headers["www-authenticate"] == "APIKey"


def test_the_right_key_is_accepted_in_any_letter_case_of_the_header_name(monkeypatch):
    monkeypatch.setattr(api, "list_documents", lambda conn: [])
    client = TestClient(_app())
    assert client.get("/documents", headers=GOOD).json() == []
    assert client.get("/documents", headers={"x-api-key": KEY}).status_code == 200


def test_the_key_is_compared_as_bytes_with_compare_digest(monkeypatch):
    seen = []
    real = api.secrets.compare_digest

    def spy(a, b):
        seen.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(api.secrets, "compare_digest", spy)
    client = TestClient(_app())
    # a non-ASCII key would raise TypeError (a 500) if compared as str (V72)
    non_ascii = {"X-API-Key": "café".encode()}
    assert client.get("/documents", headers=non_ascii).status_code == 401
    assert seen and set(seen) == {(bytes, bytes)}


def test_every_route_except_health_needs_the_key():
    app = _app()
    client = TestClient(app)
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path != "/health":
            method = sorted(route.methods)[0]
            response = client.request(method, route.path.replace("{document_id}", "1"))
            assert response.status_code == 401, route.path


@pytest.mark.parametrize("value", [None, "", "   "])
def test_the_app_refuses_to_start_without_a_key(monkeypatch, value):
    monkeypatch.delenv("AGILA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AGILA_API_KEY"):
        api.create_app(value, warm_up=_no_warm_up)


def test_the_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGILA_API_KEY", KEY)
    app = api.create_app(warm_up=_no_warm_up)
    app.dependency_overrides[api.connection] = lambda: None
    monkeypatch.setattr(api, "list_documents", lambda conn: [])
    assert TestClient(app).get("/documents", headers=GOOD).status_code == 200


def test_main_prints_one_sentence_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("AGILA_API_KEY", raising=False)
    assert api.main(run=lambda *a, **k: pytest.fail("must not start")) == 1
    assert capsys.readouterr().out.startswith("Missing environment variable AGILA_API_KEY.")


def test_main_serves_on_loopback_port_8000(monkeypatch):
    monkeypatch.setenv("AGILA_API_KEY", KEY)
    monkeypatch.delenv("AGILA_HOST", raising=False)
    seen = {}
    assert api.main(run=lambda app, **kwargs: seen.update(kwargs)) == 0
    assert seen == {"host": "127.0.0.1", "port": 8000}


def test_main_listens_on_agila_host_when_it_is_set(monkeypatch):
    # The container sets 0.0.0.0; Compose still publishes only 127.0.0.1:8000 (V81)
    monkeypatch.setenv("AGILA_API_KEY", KEY)
    monkeypatch.setenv("AGILA_HOST", "0.0.0.0")
    seen = {}
    assert api.main(run=lambda app, **kwargs: seen.update(kwargs)) == 0
    assert seen == {"host": "0.0.0.0", "port": 8000}


# --- open pages: /health and /docs ---


def test_health_needs_no_key_and_says_ok(healthy):
    response = TestClient(_app()).get("/health")
    assert (response.status_code, response.json()) == (200, {"database": "ok", "ollama": "ok"})


def test_health_names_what_is_down(monkeypatch):
    monkeypatch.setattr(db, "check_database", lambda: None)
    monkeypatch.setattr(llm, "check_ollama", lambda: llm.OLLAMA_DOWN)
    response = TestClient(_app()).get("/health")
    assert response.status_code == 503
    assert response.json() == {"database": "ok", "ollama": llm.OLLAMA_DOWN}
    monkeypatch.setattr(db, "check_database", lambda: db.DATABASE_DOWN)
    assert TestClient(_app()).get("/health").json()["database"] == db.DATABASE_DOWN


def test_docs_and_the_openapi_page_need_no_key():
    client = TestClient(_app())
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"] == {
        "APIKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }
    assert "security" not in spec["paths"]["/health"]["get"]
    assert spec["paths"]["/ask"]["post"]["security"] == [{"APIKeyHeader": []}]


# --- plain def everywhere (decision 2) ---


def test_no_route_or_dependency_of_ours_is_async():
    app = _app()
    ours = [r.endpoint for r in app.routes if isinstance(r, APIRoute)]
    ours += [api.connection, app.state.require_key]
    assert len(ours) >= 8
    for function in ours:
        assert not inspect.iscoroutinefunction(function), function.__name__
        assert not inspect.isasyncgenfunction(function), function.__name__


def test_a_second_ask_is_told_busy_at_once_while_health_still_answers(no_database, healthy):
    entered, release = threading.Event(), threading.Event()

    class SlowModel:
        def chat(self, messages):
            entered.set()
            release.wait(10)
            return llm.Reply(ANSWER, 1000)

    first = {}
    with TestClient(_app(SlowModel())) as client:  # one event loop for all requests

        def ask_first():
            first["response"] = client.post("/ask", json={"question": "Q?"}, headers=GOOD)

        thread = threading.Thread(target=ask_first)
        thread.start()
        assert entered.wait(10)
        started = time.perf_counter()
        second = client.post("/ask", json={"question": "Q?"}, headers=GOOD).json()
        health = client.get("/health")
        waited = time.perf_counter() - started
        release.set()
        thread.join(10)
    assert (second["kind"], second["note"]) == ("busy", llm.BUSY)
    assert second["passages"][0]["chunk_id"] == 11
    assert health.status_code == 200
    assert waited < 5  # neither waited for the first ask
    assert first["response"].json()["kind"] == "answer"
    assert no_database == [("busy", "web"), ("answer", "web")]


# --- warm-up (decision 5) ---


def test_the_warm_up_starts_in_the_background_at_startup():
    started = threading.Event()
    app = api.create_app(KEY, warm_up=started.set, model=ScriptedModel())
    with TestClient(app):
        assert started.wait(5)


def test_a_slow_warm_up_does_not_hold_up_startup(healthy):
    release = threading.Event()
    app = api.create_app(KEY, warm_up=lambda: release.wait(10), model=ScriptedModel())
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    finally:
        release.set()


# --- routes ---


def test_ask_returns_the_answer_its_citations_and_the_plain_text(no_database):
    response = TestClient(_app(ScriptedModel(ANSWER))).post(
        "/ask", json={"question": "What does it say?"}, headers=GOOD
    )
    body = response.json()
    assert (response.status_code, body["kind"], body["text"]) == (200, "answer", "It says so.")
    assert body["citations"][0]["quote"] == "Short passage text."
    assert body["formatted"].startswith("It says so.\n\nSources:")
    assert no_database == [("answer", "web")]


def test_a_blank_question_is_one_400_sentence():
    client = TestClient(_app())
    response = client.post("/ask", json={"question": "  "}, headers=GOOD)
    assert response.json() == {"detail": "Type a question to search for."}
    assert response.status_code == 400
    assert client.get("/search", params={"question": " "}, headers=GOOD).status_code == 400


def test_search_returns_passages_and_writes_no_log(monkeypatch):
    seen = {}

    def fake_search(conn, question, min_similarity, embedder):
        seen["min_similarity"] = min_similarity
        return SearchResult([PASSAGE], 0.8, min_similarity)

    monkeypatch.setattr(api, "search", fake_search)
    monkeypatch.setattr(questions, "record", lambda *a: pytest.fail("search must not log"))
    body = TestClient(_app()).get("/search", params={"question": "Q?"}, headers=GOOD).json()
    assert body["passages"][0]["chunk_id"] == 11
    assert seen["min_similarity"] == 0.70


def test_a_refused_save_is_one_400_sentence():
    response = TestClient(_app()).post(
        "/save/url", json={"url": "htp://example.test/a"}, headers=GOOD
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Only http and https links")


def test_a_database_that_is_down_is_one_503_sentence(monkeypatch):
    def refused(**kwargs):
        raise db.psycopg.OperationalError("connection refused")

    monkeypatch.setattr(db, "connect", refused)
    app = api.create_app(KEY, warm_up=_no_warm_up)
    response = TestClient(app).get("/documents", headers=GOOD)
    assert (response.status_code, response.json()) == (503, {"detail": db.DATABASE_DOWN})


# --- database: the API's ask writes one `web` row (FR35) ---

UNIT = np.zeros(384, dtype=np.float32)
UNIT[0] = 1.0


class SameVectorEmbedder:
    def query_embed(self, query):
        return iter([UNIT.copy()])

    def passage_embed(self, texts):
        return (UNIT.copy() for _ in texts)


class CitesTheFirstPassage:
    """Fake model: answers from whatever chunk id the prompt holds first."""

    def chat(self, messages):
        chunk_id = int(messages[-1]["content"].split('chunk_id="')[1].split('"')[0])
        return llm.Reply(ANSWER.replace('"chunk_id": 11', f'"chunk_id": {chunk_id}'), 1000)


@pytest.mark.db
def test_save_ask_list_and_delete_through_the_api_with_one_web_log_row(conn, empty_db):
    app = api.create_app(
        KEY, warm_up=_no_warm_up, model=CitesTheFirstPassage(), embedder=SameVectorEmbedder()
    )

    def test_connection():
        with db.connect(dbname=empty_db) as c:
            yield c

    app.dependency_overrides[api.connection] = test_connection
    client = TestClient(app)
    note = {"title": "Note", "label": "L", "text": TEXT}
    saved = client.post("/save/text", json=note, headers=GOOD).json()
    assert saved["message"] == "Saved Note: 1 chunks"
    chunk = conn.execute("SELECT id FROM chunks").fetchone()[0]
    body = client.post("/ask", json={"question": "Q?"}, headers=GOOD).json()
    assert (body["kind"], body["citations"][0]["chunk_id"]) == ("answer", chunk)
    rows = conn.execute("SELECT channel, chunk_ids, status FROM query_log").fetchall()
    assert rows == [("web", [chunk], "answered")]
    assert conn.execute("SELECT last_asked_at IS NOT NULL FROM documents").fetchone() == (True,)
    assert [d["title"] for d in client.get("/documents", headers=GOOD).json()] == ["Note"]
    deleted = client.delete(
        f"/documents/{saved['document_id']}", params={"confirm": "true"}, headers=GOOD
    ).json()
    assert deleted["message"] == f'Deleted document {saved["document_id"]} "Note" and its 1 chunks.'
    assert client.get("/documents", headers=GOOD).json() == []


def _note(conn):
    document = conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
        " content_hash) VALUES ((SELECT id FROM spaces LIMIT 1), 'Note', 'text', 'L', 'text:L',"
        " 'h') RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO chunks (document_id, position, text, embedding) VALUES (%s, 0, %s, %s)",
        (document, TEXT, UNIT),
    )
    conn.commit()
    return document


def _client(empty_db):
    app = api.create_app(KEY, warm_up=_no_warm_up, model=ScriptedModel())

    def test_connection():
        with db.connect(dbname=empty_db) as c:
            yield c

    app.dependency_overrides[api.connection] = test_connection
    return TestClient(app)


def _counts(conn):
    return conn.execute(
        "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)"
    ).fetchone()


@pytest.mark.db
def test_delete_without_confirm_shows_the_document_and_deletes_nothing(conn, empty_db):
    document = _note(conn)
    response = _client(empty_db).delete(f"/documents/{document}", headers=GOOD)
    body = response.json()
    assert response.status_code == 200
    assert (body["deleted"], body["title"], body["source_type"], body["chunk_count"]) == (
        False,
        "Note",
        "text",
        1,
    )
    assert body["saved_at"]
    assert body["message"] == (
        f'Would delete document {document} "Note" (text, 1 chunks). Nothing deleted.'
        " Send it again with confirm=true to delete it."
    )
    assert _counts(conn) == (1, 1)
    false = _client(empty_db).delete(
        f"/documents/{document}", params={"confirm": "false"}, headers=GOOD
    )
    assert false.json()["deleted"] is False
    assert _counts(conn) == (1, 1)


@pytest.mark.db
def test_delete_with_confirm_removes_the_document_and_its_chunks(conn, empty_db):
    document = _note(conn)
    response = _client(empty_db).delete(
        f"/documents/{document}", params={"confirm": "true"}, headers=GOOD
    )
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["message"] == f'Deleted document {document} "Note" and its 1 chunks.'
    assert _counts(conn) == (0, 0)


@pytest.mark.db
@pytest.mark.parametrize("confirm", ["false", "true"])
def test_delete_of_an_unknown_id_is_404_with_one_sentence(conn, empty_db, confirm):
    response = _client(empty_db).delete(
        "/documents/999", params={"confirm": confirm}, headers=GOOD
    )
    assert (response.status_code, response.json()) == (404, {"detail": "No document with id 999."})
