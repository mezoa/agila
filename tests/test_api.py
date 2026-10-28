import inspect
import json
import threading
import time
from datetime import UTC, datetime

import numpy as np
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from agila import api, db, export, library, llm, questions
from agila.ask import format_search
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

    def one_passage(conn, question, embedder=None, include_private=True):
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
    monkeypatch.setattr(api, "list_documents", lambda conn, *args, **kwargs: [])
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


def test_archive_needs_the_key():
    paths = {(r.path, *r.methods) for r in _app().routes if isinstance(r, APIRoute)}
    assert ("/documents/{document_id}/archive", "POST") in paths
    assert TestClient(_app()).post("/documents/1/archive").status_code == 401


def test_documents_status_must_be_active_archived_or_all(monkeypatch):
    seen = []
    def record(conn, status, include_private):
        seen.append(status)
        return []

    monkeypatch.setattr(api, "list_documents", record)
    client = TestClient(_app())
    assert client.get("/documents", headers=GOOD).status_code == 200
    for status in ("active", "archived", "all"):
        assert client.get("/documents", params={"status": status}, headers=GOOD).json() == []
    assert seen == ["all", "active", "archived", "all"]  # `all` is the default (RQ3)
    for bad in ("superseded", "ACTIVE", ""):
        response = client.get("/documents", params={"status": bad}, headers=GOOD)
        assert response.status_code == 422, bad
    assert len(seen) == 4


@pytest.mark.parametrize("value", [None, "", "   "])
def test_the_app_refuses_to_start_without_a_key(monkeypatch, value):
    monkeypatch.delenv("AGILA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AGILA_API_KEY"):
        api.create_app(value, warm_up=_no_warm_up)


def test_the_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGILA_API_KEY", KEY)
    app = api.create_app(warm_up=_no_warm_up)
    app.dependency_overrides[api.connection] = lambda: None
    monkeypatch.setattr(api, "list_documents", lambda conn, *args, **kwargs: [])
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
    # access_log off: GET /search carries the question in its URL (NFR8, DEVIATIONS 55)
    assert seen == {"host": "127.0.0.1", "port": 8000, "access_log": False}


def test_main_listens_on_agila_host_when_it_is_set(monkeypatch):
    # The container sets 0.0.0.0; Compose still publishes only 127.0.0.1:8000 (V81)
    monkeypatch.setenv("AGILA_API_KEY", KEY)
    monkeypatch.setenv("AGILA_HOST", "0.0.0.0")
    seen = {}
    assert api.main(run=lambda app, **kwargs: seen.update(kwargs)) == 0
    assert seen == {"host": "0.0.0.0", "port": 8000, "access_log": False}


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

    def fake_search(conn, question, min_similarity, embedder, include_private):
        seen["min_similarity"] = min_similarity
        return SearchResult([PASSAGE], 0.8, min_similarity)

    monkeypatch.setattr(api, "search", fake_search)
    monkeypatch.setattr(questions, "record", lambda *a: pytest.fail("search must not log"))
    body = TestClient(_app()).get("/search", params={"question": "Q?"}, headers=GOOD).json()
    assert body["passages"][0]["chunk_id"] == 11
    assert seen["min_similarity"] == 0.68
    # the same text the CLI's `search` prints (one formatter, Eo's Q3)
    assert body["formatted"] == format_search(SearchResult([PASSAGE], 0.8, 0.68))
    assert body["formatted"].startswith("1. 0.80  llm-wiki  (https://example.test, saved ")


def test_search_formatted_says_nothing_close_enough(monkeypatch):
    monkeypatch.setattr(api, "search", lambda conn, q, min_similarity, embedder, **kwargs: (
        SearchResult([], 0.402, min_similarity)
    ))
    body = TestClient(_app()).get("/search", params={"question": "Q?"}, headers=GOOD).json()
    assert body["formatted"] == (
        "Nothing close enough: the best similarity was 0.40, below the threshold 0.68."
    )


# --- the channel header (DEVIATIONS 54) ---


def test_ask_without_the_channel_header_logs_web(no_database):
    TestClient(_app(ScriptedModel(ANSWER))).post("/ask", json={"question": "Q?"}, headers=GOOD)
    assert no_database == [("answer", "web")]


def test_ask_with_the_discord_channel_header_logs_discord(no_database):
    headers = GOOD | {"X-Agila-Channel": "discord"}
    response = TestClient(_app(ScriptedModel(ANSWER))).post(
        "/ask", json={"question": "Q?"}, headers=headers
    )
    assert response.status_code == 200
    assert no_database == [("answer", "discord")]


@pytest.mark.parametrize("value", ["cli", "Discord", "x", ""])
def test_an_unknown_channel_is_one_400_sentence_and_nothing_is_asked(no_database, value):
    model = ScriptedModel(ANSWER)
    headers = GOOD | {"X-Agila-Channel": value}
    response = TestClient(_app(model)).post("/ask", json={"question": "Q?"}, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": f'Unknown channel "{value}"; use web, discord or n8n.'}
    assert (no_database, model.calls) == ([], 0)


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
    assert saved["export_warning"] is None  # FR28: the note was written (DEVIATIONS 52)
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
    assert deleted["export_warning"] is None
    assert client.get("/documents", headers=GOOD).json() == []


@pytest.mark.db
def test_an_ask_from_the_bot_writes_one_discord_log_row(conn, empty_db):
    app = api.create_app(
        KEY, warm_up=_no_warm_up, model=CitesTheFirstPassage(), embedder=SameVectorEmbedder()
    )

    def test_connection():
        with db.connect(dbname=empty_db) as c:
            yield c

    app.dependency_overrides[api.connection] = test_connection
    client = TestClient(app)
    client.post("/save/text", json={"title": "Note", "label": "L", "text": TEXT}, headers=GOOD)
    headers = GOOD | {"X-Agila-Channel": "discord"}
    assert client.post("/ask", json={"question": "Q?"}, headers=headers).status_code == 200
    rows = conn.execute("SELECT channel, status FROM query_log").fetchall()
    assert rows == [("discord", "answered")]


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


# --- database: list by status, archive (block o part 2) ---


def _saving_client(empty_db):
    """Like `_client`, but saves embed with the fake embedder (no model is loaded)."""
    app = api.create_app(
        KEY, warm_up=_no_warm_up, model=ScriptedModel(), embedder=SameVectorEmbedder()
    )

    def test_connection():
        with db.connect(dbname=empty_db) as c:
            yield c

    app.dependency_overrides[api.connection] = test_connection
    return TestClient(app)


@pytest.mark.db
def test_documents_list_has_source_type_and_saved_date(conn, empty_db):
    document = _note(conn)
    (saved_at,) = conn.execute("SELECT saved_at FROM documents").fetchone()
    conn.commit()
    (item,) = _client(empty_db).get("/documents", headers=GOOD).json()
    assert (item["document_id"], item["source_type"]) == (document, "text")
    assert item["saved_date"] == export.local_date(saved_at)  # the laptop's date, YYYY-MM-DD


@pytest.mark.db
def test_documents_list_filters_by_status(conn, empty_db):
    client = _saving_client(empty_db)
    kept_note = {"title": "Kept", "label": "k", "text": TEXT}
    kept = client.post("/save/text", json=kept_note, headers=GOOD).json()
    client.post("/save/text", json={"title": "Live", "label": "l", "text": TEXT}, headers=GOOD)
    client.post(f"/documents/{kept['document_id']}/archive", headers=GOOD)

    def titles(**params):
        return [d["title"] for d in client.get("/documents", params=params, headers=GOOD).json()]

    assert titles(status="active") == ["Live"]
    assert titles(status="archived") == ["Kept"]
    assert titles() == titles(status="all") == ["Live", "Kept"]


@pytest.mark.db
def test_archive_returns_title_and_the_cli_sentence(conn, empty_db):
    document = _note(conn)
    response = _client(empty_db).post(f"/documents/{document}/archive", headers=GOOD)
    assert response.status_code == 200
    assert response.json() == {
        "title": "Note",
        "export_warning": None,
        "message": f'Archived document {document} "Note".',
    }
    assert conn.execute("SELECT status FROM documents").fetchone() == ("archived",)


@pytest.mark.db
def test_archive_of_an_archived_document_is_400_with_the_library_sentence(conn, empty_db):
    document = _note(conn)
    client = _client(empty_db)
    client.post(f"/documents/{document}/archive", headers=GOOD)
    response = client.post(f"/documents/{document}/archive", headers=GOOD)
    assert (response.status_code, response.json()) == (
        400,
        {"detail": f"Document {document} is archived; only active documents can be archived."},
    )


@pytest.mark.db
def test_archive_of_an_unknown_id_is_404(conn, empty_db):
    response = _client(empty_db).post("/documents/999/archive", headers=GOOD)
    assert (response.status_code, response.json()) == (404, {"detail": "No document with id 999."})


@pytest.mark.db
def test_archive_rewrites_the_note_status(conn, empty_db, vault):
    client = _saving_client(empty_db)
    note_body = {"title": "Note", "label": "L", "text": TEXT}
    saved = client.post("/save/text", json=note_body, headers=GOOD).json()
    note = vault / export.note_name("Note", saved["document_id"])
    assert "status: active" in note.read_text(encoding="utf-8")
    body = client.post(f"/documents/{saved['document_id']}/archive", headers=GOOD).json()
    assert body["export_warning"] is None
    assert "status: archived" in note.read_text(encoding="utf-8")


# --- FR41: private documents never reach discord or n8n (block p) ---

PRIVATE_TEXT = "Private passage about the vault code. It stays on the laptop."
PUBLIC_TEXT = "Public passage about the vault code. Anyone may read it."
SECRET = "Secret plans"
DISCORD = GOOD | {"X-Agila-Channel": "discord"}
N8N = GOOD | {"X-Agila-Channel": "n8n"}
WEB = GOOD | {"X-Agila-Channel": "web"}


@pytest.mark.parametrize(
    ("headers", "sees"),
    [(GOOD, True), (WEB, True), (DISCORD, False), (N8N, False)],
    ids=["no header", "web", "discord", "n8n"],
)
def test_only_web_sees_private_documents_in_the_list(monkeypatch, headers, sees):
    seen = []

    def record(conn, status, include_private):
        seen.append(include_private)
        return []

    monkeypatch.setattr(api, "list_documents", record)
    response = TestClient(_app()).get("/documents", headers=headers)
    assert (response.status_code, seen) == (200, [sees])


def test_ask_from_n8n_is_one_400_sentence_and_nothing_is_asked(no_database):
    model = ScriptedModel(ANSWER)
    response = TestClient(_app(model)).post("/ask", json={"question": "Q?"}, headers=N8N)
    assert (response.status_code, response.json()) == (
        400,
        {"detail": "The n8n channel cannot ask questions; use web or discord."},
    )
    assert (no_database, model.calls) == ([], 0)


def _private_and_public(conn):
    """A private note saved first (lower chunk id, so it would come first without the filter),
    then a public one; both have the same vector."""
    private = library.save_text(
        conn, SECRET, "secret", PRIVATE_TEXT, SameVectorEmbedder(), private=True
    )
    public = library.save_text(conn, "Public note", "public", PUBLIC_TEXT, SameVectorEmbedder())
    chunk = dict(conn.execute("SELECT document_id, id FROM chunks").fetchall())
    conn.commit()
    return private.document_id, chunk[private.document_id], chunk[public.document_id]


def _asking_client(empty_db):
    app = api.create_app(
        KEY, warm_up=_no_warm_up, model=CitesTheFirstPassage(), embedder=SameVectorEmbedder()
    )

    def test_connection():
        with db.connect(dbname=empty_db) as c:
            yield c

    app.dependency_overrides[api.connection] = test_connection
    return TestClient(app)


def _never_shown(body) -> None:
    text = json.dumps(body)
    for leak in (SECRET, "Private passage", "secret"):
        assert leak not in text


@pytest.mark.db
def test_ask_from_discord_never_cites_or_shows_a_private_document(conn, empty_db):
    _, private_chunk, public_chunk = _private_and_public(conn)
    client = _asking_client(empty_db)
    web = client.post("/ask", json={"question": "Q?"}, headers=GOOD).json()
    assert web["citations"][0]["chunk_id"] == private_chunk  # the laptop still sees it
    body = client.post("/ask", json={"question": "Q?"}, headers=DISCORD).json()
    assert body["kind"] == "answer"
    assert [c["chunk_id"] for c in body["citations"]] == [public_chunk]
    assert [p["chunk_id"] for p in body["passages"]] == [public_chunk]
    _never_shown(body)  # answer, citations, passages and `formatted`
    rows = conn.execute("SELECT channel, chunk_ids FROM query_log ORDER BY id").fetchall()
    assert rows == [("web", [private_chunk, public_chunk]), ("discord", [public_chunk])]


@pytest.mark.db
@pytest.mark.parametrize("headers", [DISCORD, N8N], ids=["discord", "n8n"])
def test_search_route_hides_private_passages_from_discord(conn, empty_db, headers):
    _, private_chunk, public_chunk = _private_and_public(conn)
    client = _asking_client(empty_db)
    body = client.get("/search", params={"question": "Q?"}, headers=headers).json()
    assert [p["chunk_id"] for p in body["passages"]] == [public_chunk]
    _never_shown(body)
    web = client.get("/search", params={"question": "Q?"}, headers=GOOD).json()
    assert [p["chunk_id"] for p in web["passages"]] == [private_chunk, public_chunk]


@pytest.mark.db
def test_documents_list_omits_private_documents_for_discord_and_n8n(conn, empty_db):
    _private_and_public(conn)
    client = _client(empty_db)
    for headers in (DISCORD, N8N):
        for status in ("active", "all"):
            body = client.get("/documents", params={"status": status}, headers=headers).json()
            assert [d["title"] for d in body] == ["Public note"]  # not counted either
            _never_shown(body)


@pytest.mark.db
def test_documents_list_still_lists_private_documents_for_web(conn, empty_db):
    _private_and_public(conn)
    client = _client(empty_db)
    for headers in (GOOD, WEB):
        body = client.get("/documents", headers=headers).json()
        assert [(d["title"], d["visibility"]) for d in body] == [
            ("Public note", "anywhere"),
            (SECRET, "laptop_only"),
        ]


@pytest.mark.db
@pytest.mark.parametrize("headers", [DISCORD, N8N], ids=["discord", "n8n"])
def test_archive_of_a_private_document_from_discord_is_404_and_changes_nothing(
    conn, empty_db, headers
):
    private, _, _ = _private_and_public(conn)
    response = _client(empty_db).post(f"/documents/{private}/archive", headers=headers)
    assert (response.status_code, response.json()) == (
        404,
        {"detail": f"No document with id {private}."},
    )
    assert conn.execute(
        "SELECT status FROM documents WHERE id = %s", (private,)
    ).fetchone() == ("active",)


@pytest.mark.db
@pytest.mark.parametrize("confirm", ["false", "true"])
@pytest.mark.parametrize("headers", [DISCORD, N8N], ids=["discord", "n8n"])
def test_delete_of_a_private_document_from_discord_is_404_with_and_without_confirm(
    conn, empty_db, headers, confirm
):
    private, _, _ = _private_and_public(conn)
    before = _counts(conn)
    response = _client(empty_db).delete(
        f"/documents/{private}", params={"confirm": confirm}, headers=headers
    )
    assert (response.status_code, response.json()) == (
        404,
        {"detail": f"No document with id {private}."},
    )
    _never_shown(response.json())
    assert _counts(conn) == before


@pytest.mark.db
@pytest.mark.parametrize("headers", [DISCORD, N8N], ids=["discord", "n8n"])
@pytest.mark.parametrize(
    "text", [PRIVATE_TEXT, "Other words for the same label."], ids=["unchanged", "same label"]
)
def test_save_from_discord_matching_a_private_document_is_400_without_its_title(
    conn, empty_db, headers, text
):
    _private_and_public(conn)
    before = _counts(conn)
    note = {"title": "Bot title", "label": "secret", "text": text}
    response = _asking_client(empty_db).post("/save/text", json=note, headers=headers)
    assert (response.status_code, response.json()) == (
        400,
        {
            "detail": "A private document already uses this link or label;"
            " save it from the laptop."
        },
    )
    _never_shown(response.json())
    assert _counts(conn) == before


@pytest.mark.db
def test_a_web_save_matching_a_private_document_behaves_as_on_the_laptop(conn, empty_db):
    private, _, _ = _private_and_public(conn)
    note = {"title": SECRET, "label": "secret", "text": PRIVATE_TEXT}
    body = _asking_client(empty_db).post("/save/text", json=note, headers=GOOD).json()
    assert body["message"] == f"Already saved, unchanged: {SECRET} (document {private})."


# --- FR39: /stale (block q) ---

LAPTOP_ONLY = "include_private=true is allowed only from the laptop."


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_stale_limit_must_be_1_to_100(limit):
    response = TestClient(_app()).get("/stale", params={"limit": limit}, headers=GOOD)
    assert response.status_code == 422


def test_stale_needs_the_key():
    assert TestClient(_app()).get("/stale").status_code == 401


@pytest.mark.parametrize("headers", [DISCORD, N8N], ids=["discord", "n8n"])
def test_stale_include_private_from_discord_or_n8n_is_refused_before_the_database(
    monkeypatch, headers
):
    monkeypatch.setattr(api, "find_stale", lambda *a, **k: pytest.fail("must not search"))
    params = {"include_private": "true"}
    response = TestClient(_app()).get("/stale", params=params, headers=headers)
    assert (response.status_code, response.json()) == (400, {"detail": LAPTOP_ONLY})


def _backdated(conn, title, age, visibility="anywhere"):
    """A document saved `age` ago by the database clock (the route uses the real `now`)."""
    conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_label, identity_key,"
        " content_hash, saved_at, visibility) VALUES ((SELECT id FROM spaces LIMIT 1), %s,"
        " 'text', %s, %s, 'h', now() - %s::interval, %s)",
        (title, title, f"text:{title}", age, visibility),
    )
    conn.commit()


@pytest.mark.db
def test_stale_route_returns_documents_total_and_formatted(conn, empty_db):
    _backdated(conn, "Old page", "40 days")
    _backdated(conn, "Ancient page", "13 months")
    _backdated(conn, "Fresh page", "2 days")
    body = _client(empty_db).get("/stale", headers=GOOD).json()
    assert [(d["title"], d["reason"]) for d in body["documents"]] == [
        ("Ancient page", "older than 12 months"),
        ("Old page", "never asked"),
    ]
    assert body["total"] == 2
    lines = body["formatted"].splitlines()
    assert lines[0] == "Stale documents: 2."
    assert lines[1].endswith("  text  Ancient page  (older than 12 months)")
    assert set(body["documents"][0]) == {
        "document_id",
        "title",
        "source_type",
        "saved_at",
        "last_asked_at",
        "reason",
    }


@pytest.mark.db
def test_stale_route_with_nothing_stale_says_so(conn, empty_db):
    _backdated(conn, "Fresh page", "2 days")
    body = _client(empty_db).get("/stale", headers=N8N).json()
    assert body == {"documents": [], "total": 0, "formatted": "Nothing stale this week"}


@pytest.mark.db
def test_stale_route_cuts_at_the_limit_and_says_how_many_exist(conn, empty_db):
    for n in range(3):
        _backdated(conn, f"Old {n}", f"{40 + n} days")
    body = _client(empty_db).get("/stale", params={"limit": 2}, headers=GOOD).json()
    assert (len(body["documents"]), body["total"]) == (2, 3)
    assert body["formatted"].endswith("Showing 2 of 3. Use the CLI stale for all.")


@pytest.mark.db
@pytest.mark.parametrize("headers", [DISCORD, N8N], ids=["discord", "n8n"])
def test_stale_from_discord_or_n8n_with_include_private_is_400(conn, empty_db, headers):
    _backdated(conn, SECRET, "13 months", "laptop_only")
    params = {"include_private": "true"}
    response = _client(empty_db).get("/stale", params=params, headers=headers)
    assert (response.status_code, response.json()) == (400, {"detail": LAPTOP_ONLY})
    plain = _client(empty_db).get("/stale", headers=headers).json()
    assert plain["total"] == 0
    _never_shown(plain)


@pytest.mark.db
def test_stale_without_a_channel_header_still_omits_private(conn, empty_db):
    _backdated(conn, SECRET, "13 months", "laptop_only")
    _backdated(conn, "Public page", "13 months")
    body = _client(empty_db).get("/stale", headers=GOOD).json()  # no header = web
    assert [d["title"] for d in body["documents"]] == ["Public page"]
    assert body["total"] == 1  # not counted either
    _never_shown(body)


@pytest.mark.db
@pytest.mark.parametrize("headers", [GOOD, WEB], ids=["no header", "web"])
def test_stale_from_web_with_include_private_lists_it(conn, empty_db, headers):
    _backdated(conn, SECRET, "13 months", "laptop_only")
    params = {"include_private": "true"}
    body = _client(empty_db).get("/stale", params=params, headers=headers).json()
    assert [d["title"] for d in body["documents"]] == [SECRET]
