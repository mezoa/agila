"""Block o step 5: the bot's API client against a fake API (httpx.MockTransport, no sockets)."""

import asyncio
import json

import httpx
import pytest

from agila.bot import client
from agila.bot.client import AgilaApi, ApiError

KEY = "test-key-not-a-secret"
QUESTION = "secret question words"


class FakeApi:
    """Answers every request with `response` (or raises it) and keeps the requests."""

    def __init__(self, response=None):
        self.response = response or httpx.Response(200, json={"ok": True})
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _run(fake, call):
    """Run one client call against `fake` and return its result (or raise its ApiError)."""

    async def go():
        api = AgilaApi(KEY, transport=httpx.MockTransport(fake))
        try:
            return await call(api)
        finally:
            await api.aclose()

    return asyncio.run(go())


def _error(fake, call) -> ApiError:
    with pytest.raises(ApiError) as caught:
        _run(fake, call)
    return caught.value


CALLS = {
    "health": lambda api: api.health(),
    "search": lambda api: api.search(QUESTION),
    "ask": lambda api: api.ask(QUESTION),
    "save_link": lambda api: api.save_link("https://example.test/a"),
    "save_text": lambda api: api.save_text("Title", "secret saved text"),
    "list_documents": lambda api: api.list_documents(),
    "archive": lambda api: api.archive(7),
    "delete": lambda api: api.delete(7),
}


# --- what every request carries ---


@pytest.mark.parametrize("name", CALLS)
def test_every_request_carries_the_key_and_the_discord_channel(name):
    fake = FakeApi()
    _run(fake, CALLS[name])
    (request,) = fake.requests
    assert request.headers["X-API-Key"] == KEY
    assert request.headers["X-Agila-Channel"] == "discord"
    assert (request.url.scheme, request.url.host, request.url.port) == ("http", "127.0.0.1", 8000)


def test_the_client_ignores_proxy_settings_from_the_environment():
    async def go():
        api = AgilaApi(KEY, transport=httpx.MockTransport(FakeApi()))
        try:
            return api._client.trust_env
        finally:
            await api.aclose()

    assert asyncio.run(go()) is False


@pytest.mark.parametrize(
    ("name", "method", "path", "read_seconds"),
    [
        ("health", "GET", "/health", 30),
        ("search", "GET", "/search", 30),
        ("ask", "POST", "/ask", 270),
        ("save_link", "POST", "/save/url", 120),
        ("save_text", "POST", "/save/text", 120),
        ("list_documents", "GET", "/documents", 30),
        ("archive", "POST", "/documents/7/archive", 30),
        ("delete", "DELETE", "/documents/7", 30),
    ],
)
def test_each_call_uses_its_route_and_timeout(name, method, path, read_seconds):
    fake = FakeApi()
    _run(fake, CALLS[name])
    (request,) = fake.requests
    assert (request.method, request.url.path) == (method, path)
    assert request.extensions["timeout"] == {
        "connect": 5.0,
        "read": read_seconds,
        "write": read_seconds,
        "pool": read_seconds,
    }


def test_search_sends_the_question_as_a_query_parameter():
    fake = FakeApi()
    _run(fake, CALLS["search"])
    assert fake.requests[0].url.params["question"] == QUESTION


def test_ask_sends_the_question_in_the_body():
    fake = FakeApi(httpx.Response(200, json={"kind": "refusal"}))
    assert _run(fake, CALLS["ask"]) == {"kind": "refusal"}
    assert json.loads(fake.requests[0].content) == {"question": QUESTION}


def test_save_link_sends_url_title_and_replace():
    fake = FakeApi()
    _run(fake, lambda api: api.save_link("https://example.test/a", "A title", replace=True))
    assert json.loads(fake.requests[0].content) == {
        "url": "https://example.test/a",
        "title": "A title",
        "replace": True,
    }


def test_save_text_label_defaults_to_the_title():
    fake = FakeApi()
    _run(fake, CALLS["save_text"])
    assert json.loads(fake.requests[0].content) == {
        "title": "Title",
        "label": "Title",
        "text": "secret saved text",
        "replace": False,
    }


def test_save_text_keeps_a_given_label():
    fake = FakeApi()
    _run(fake, lambda api: api.save_text("Title", "Text.", label="my-label"))
    assert json.loads(fake.requests[0].content)["label"] == "my-label"


@pytest.mark.parametrize("status", ["active", "archived", "all"])
def test_list_documents_sends_the_status(status):
    fake = FakeApi(httpx.Response(200, json=[{"document_id": 1}]))
    assert _run(fake, lambda api: api.list_documents(status)) == [{"document_id": 1}]
    assert dict(fake.requests[0].url.params) == {"status": status}


def test_list_documents_asks_for_active_by_default():
    fake = FakeApi(httpx.Response(200, json=[]))
    _run(fake, CALLS["list_documents"])
    assert dict(fake.requests[0].url.params) == {"status": "active"}


@pytest.mark.parametrize(("confirm", "sent"), [(False, "false"), (True, "true")])
def test_delete_sends_confirm(confirm, sent):
    fake = FakeApi()
    _run(fake, lambda api: api.delete(7, confirm))
    (request,) = fake.requests
    assert (request.url.path, dict(request.url.params)) == ("/documents/7", {"confirm": sent})


def test_delete_is_a_dry_run_unless_confirmed():
    fake = FakeApi()
    _run(fake, CALLS["delete"])
    assert dict(fake.requests[0].url.params) == {"confirm": "false"}


@pytest.mark.parametrize("name", ["archive", "delete"])
def test_an_unknown_id_shows_the_api_not_found_sentence(name):
    response = httpx.Response(404, json={"detail": "No document with id 7."})
    error = _error(FakeApi(response), CALLS[name])
    assert (error.sentence, error.kind) == ("No document with id 7.", "HTTP 404")


def test_archive_sends_no_body():
    fake = FakeApi()
    _run(fake, CALLS["archive"])
    assert fake.requests[0].content == b""


def test_health_returns_the_body_also_on_503():
    body = {"database": "ok", "ollama": "Ollama is not running on the laptop."}
    assert _run(FakeApi(httpx.Response(503, json=body)), CALLS["health"]) == body


# --- every failure is one sentence and a short kind ---


@pytest.mark.parametrize("name", CALLS)
@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow connect")]
)
def test_an_api_that_is_not_running_is_one_sentence(name, failure):
    error = _error(FakeApi(failure), CALLS[name])
    assert error.sentence == client.NOT_ANSWERING
    assert error.kind == type(failure).__name__


def test_a_slow_answer_is_one_sentence_with_the_seconds():
    error = _error(FakeApi(httpx.ReadTimeout("slow")), CALLS["ask"])
    assert error.sentence == "Agila's API took longer than 270 seconds to reply."
    assert error.kind == "ReadTimeout"


def test_a_slow_save_says_it_may_still_finish():
    error = _error(FakeApi(httpx.ReadTimeout("slow")), CALLS["save_link"])
    assert error.sentence == (
        "Agila's API took longer than 120 seconds to reply."
        " The save may still finish; check before saving again."
    )


def test_a_refused_key_is_one_sentence():
    response = httpx.Response(401, json={"detail": "Missing or wrong API key."})
    error = _error(FakeApi(response), CALLS["search"])
    assert (error.sentence, error.kind) == (client.WRONG_KEY, "HTTP 401")


@pytest.mark.parametrize("status", [400, 404, 503])
def test_a_refusal_shows_the_api_sentence(status):
    detail = "Only http and https links can be saved."
    error = _error(FakeApi(httpx.Response(status, json={"detail": detail})), CALLS["save_link"])
    assert (error.sentence, error.kind) == (detail, f"HTTP {status}")


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500, text="Internal Server Error"), httpx.Response(422, json={"detail": []})],
    ids=["500", "422"],
)
def test_any_other_status_is_one_fixed_sentence(response):
    error = _error(FakeApi(response), CALLS["ask"])
    assert error.sentence == f"Agila's API answered with HTTP {response.status_code}."


def test_a_reply_that_is_not_json_is_one_sentence():
    error = _error(FakeApi(httpx.Response(200, text="<html>")), CALLS["ask"])
    assert (error.sentence, error.kind) == (client.UNREADABLE, "ValueError")


@pytest.mark.parametrize("name", CALLS)
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(401),
        httpx.Response(500, text="boom"),
    ],
    ids=["connect", "timeout", "401", "500"],
)
def test_no_sentence_or_kind_holds_the_url_question_text_or_key(name, failure):
    error = _error(FakeApi(failure), CALLS[name])
    for leak in ("127.0.0.1:8000/", "http://", QUESTION, "secret saved text", KEY):
        assert leak not in error.sentence
        assert leak not in error.kind
        assert leak not in str(error)


def test_every_client_sentence_is_at_most_25_words():
    sentences = [
        client.NOT_ANSWERING,
        client.WRONG_KEY,
        client.UNREADABLE,
        "Agila's API took longer than 120 seconds to reply." + client.SAVE_MAY_FINISH,
    ]
    assert all(len(s.split()) <= 25 for s in sentences)  # NFR7
