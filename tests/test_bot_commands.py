"""Block o step 6: the slash commands with fake interactions and a fake API (no Discord, no
network, no model, no database)."""

import asyncio
import json
import logging

import discord
import httpx
import pytest
from botfakes import EO, STRANGER, FakeInteraction, run, sent
from discord import app_commands

from agila.bot import client, commands, messages
from agila.bot.commands import AllowListTree, build_tree

PASSAGES = "1. 0.80  llm-wiki  (https://example.test, saved 2026-10-21)\n   Short passage text."
ANSWER = {
    "kind": "answer",
    "text": "It says so.",
    "note": None,
    "formatted": 'It says so.\n\nSources:\n1. "Short passage text."',
}
REFUSAL_TEXT = "I couldn't find this in your saved material."
BUSY = "Agila is answering another question right now. Try again in a minute."
QUESTION = "secret question words"


DOC = {
    "document_id": 7,
    "title": "A saved page",
    "saved_date": "2026-10-28",
    "status": "active",
    "visibility": "anywhere",
    "source_type": "web",
}


def ok(body) -> httpx.Response:
    return httpx.Response(200, json=body)


def ask_routes(answer=ANSWER, formatted=PASSAGES) -> dict:
    return {
        "GET /search": ok({"passages": [], "formatted": formatted}),
        "POST /ask": ok(answer) if isinstance(answer, dict) else answer,
    }


def _client() -> discord.Client:
    return discord.Client(intents=discord.Intents.default(), allowed_mentions=commands.NO_PINGS)


# --- FR40: the allow-list ---


def _check(allowed, user_id) -> tuple[bool, list]:
    events: list = []
    tree = AllowListTree(_client(), frozenset(allowed))
    return asyncio.run(tree.interaction_check(FakeInteraction(events, user_id))), events


def test_an_allow_listed_user_passes_the_check():
    assert _check({EO}, EO) == (True, [])


def test_anyone_else_is_ignored_with_no_response_at_all(caplog):
    caplog.set_level(logging.INFO, logger="agila.bot")
    assert _check({EO}, STRANGER) == (False, [])  # no defer, no message, no API request
    assert "ignored a request from a user not on the allow-list" in caplog.text
    assert str(STRANGER) not in caplog.text


def test_an_empty_allow_list_answers_nobody():
    assert _check(set(), EO) == (False, [])


# --- defer first, then passages, then the answer (FR27) ---

HANDLERS = {
    "ping": (commands.ping, {"GET /health": ok({"database": "ok", "ollama": "ok"})}, ()),
    "ask": (commands.ask, ask_routes(), (QUESTION,)),
    "save_link": (
        commands.save_link,
        {"POST /save/url": ok({"message": "Saved A: 2 chunks", "outcome": "saved"})},
        ("https://example.test/a",),
    ),
    "save_text": (
        commands.save_text,
        {"POST /save/text": ok({"message": "Saved T: 1 chunks", "outcome": "saved"})},
        ("T", "secret saved text"),
    ),
    "list": (commands.list_documents, {"GET /documents": ok([])}, ()),
    "archive": (
        commands.archive,
        {"POST /documents/7/archive": ok({"title": "T", "message": 'Archived document 7 "T".'})},
        (7,),
    ),
    "delete": (
        commands.delete,
        {"DELETE /documents/7": ok({"deleted": False, "message": "Would delete document 7."})},
        (7,),
    ),
}


@pytest.mark.parametrize("name", HANDLERS)
def test_every_command_defers_before_anything_else(name):
    handler, routes, args = HANDLERS[name]
    events, _ = run(handler, routes, *args)
    assert events[0] == ("defer", {"thinking": True})
    assert [e[0] for e in events].count("defer") == 1


def test_ask_posts_the_passages_first_and_the_answer_second():
    events, fake = run(commands.ask, ask_routes(), QUESTION)
    assert [(e[0], e[1] if e[0] == "request" else None) for e in events] == [
        ("defer", None),
        ("request", "GET /search"),
        ("edit", None),
        ("request", "POST /ask"),
        ("followup", None),
    ]
    assert sent(events) == [PASSAGES, ANSWER["formatted"]]
    assert json.loads(fake.bodies["POST /ask"]) == {"question": QUESTION}


def test_ask_still_asks_when_nothing_was_found_so_the_question_is_logged():
    nothing = "Nothing close enough: the best similarity was 0.40, below the threshold 0.68."
    refusal = {"kind": "refusal", "text": REFUSAL_TEXT, "note": None, "formatted": REFUSAL_TEXT}
    events, _ = run(commands.ask, ask_routes(refusal, formatted=nothing), QUESTION)
    assert ("request", "POST /ask") in events
    assert sent(events) == [nothing, REFUSAL_TEXT]


@pytest.mark.parametrize("kind", ["passages", "busy"])
def test_ask_shows_only_the_note_for_the_fallback_and_busy(kind):
    reply = {"kind": kind, "text": "", "note": BUSY, "formatted": BUSY + "\n\nClosest passages:"}
    events, _ = run(commands.ask, ask_routes(reply), QUESTION)
    assert sent(events) == [PASSAGES, BUSY]


def test_an_api_that_is_down_at_search_gives_one_sentence_and_no_ask():
    routes = ask_routes()
    routes["GET /search"] = httpx.ConnectError("refused")
    events, _ = run(commands.ask, routes, QUESTION)
    assert ("request", "POST /ask") not in events
    assert [e[0] for e in events] == ["defer", "request", "edit"]
    assert sent(events) == [client.NOT_ANSWERING]


def test_a_slow_answer_after_the_passages_is_a_follow_up_sentence():
    events, _ = run(commands.ask, ask_routes(httpx.ReadTimeout("slow")), QUESTION)
    assert sent(events) == [PASSAGES, "Agila's API took longer than 270 seconds to reply."]
    assert events[-1][0] == "followup"


def test_a_long_answer_arrives_as_several_follow_ups_in_order():
    long = dict(ANSWER, formatted="word " * 900)  # 4,500 characters
    events, _ = run(commands.ask, ask_routes(long), QUESTION)
    follow_ups = [e[1]["content"] for e in events if e[0] == "followup"]
    assert [len(p) for p in follow_ups] == [1899, 1899, 699]
    assert " ".join(follow_ups).split() == ["word"] * 900


def test_long_passages_fill_the_first_message_then_follow_ups():
    events, _ = run(commands.ask, ask_routes(formatted="p" * 2500), QUESTION)
    assert [e[0] for e in events if e[0] in ("edit", "followup")] == [
        "edit",
        "followup",
        "followup",
    ]


# --- no pings (FR27) ---

PINGS = "Hello @everyone and <@123> and <@&456>."


@pytest.mark.parametrize("name", HANDLERS)
def test_every_message_is_sent_with_mentions_that_parse_nothing(name):
    handler, routes, args = HANDLERS[name]
    routes = {
        "GET /health": ok({"database": PINGS, "ollama": "ok"}),
        "GET /search": ok({"formatted": PINGS}),
        "POST /ask": ok(dict(ANSWER, formatted=PINGS)),
        "POST /save/url": ok({"message": PINGS, "outcome": "saved"}),
        "POST /save/text": ok({"message": PINGS, "outcome": "saved"}),
        "GET /documents": ok([DOC | {"title": PINGS}]),
        "POST /documents/7/archive": ok({"title": PINGS, "message": PINGS}),
        "DELETE /documents/7": ok({"deleted": False, "message": PINGS}),
    }
    events, _ = run(handler, routes, *args)
    messages = [e[1] for e in events if e[0] in ("edit", "followup")]
    assert messages and all(PINGS in m["content"] for m in messages)
    assert all(m["allowed_mentions"].to_dict() == {"parse": []} for m in messages)


# --- /save and /ping ---


@pytest.mark.parametrize(
    "message",
    [
        "Already saved, unchanged: A (document 12).",
        "Saved A: 2 chunks. It replaces document 12, now superseded.",
    ],
)
def test_save_link_shows_the_api_sentence(message):
    routes = {"POST /save/url": ok({"message": message, "outcome": "x"})}
    events, fake = run(commands.save_link, routes, "https://example.test/a", "A", True)
    assert sent(events) == [message]
    assert json.loads(fake.bodies["POST /save/url"]) == {
        "url": "https://example.test/a",
        "title": "A",
        "replace": True,
    }


def test_a_refused_save_shows_the_api_refusal():
    detail = "Only http and https links can be saved."
    routes = {"POST /save/url": httpx.Response(400, json={"detail": detail})}
    events, _ = run(commands.save_link, routes, "htp://example.test")
    assert sent(events) == [detail]


def test_save_text_sends_the_title_as_label_when_none_is_given():
    routes = {"POST /save/text": ok({"message": "Saved T: 1 chunks", "warning": "Warning: x."})}
    events, fake = run(commands.save_text, routes, "T", "Three. Short. Sentences.")
    assert json.loads(fake.bodies["POST /save/text"]) == {
        "title": "T",
        "label": "T",
        "text": "Three. Short. Sentences.",
        "replace": False,
    }
    assert sent(events) == ["Saved T: 1 chunks\nWarning: x."]


def test_ping_shows_pong_and_the_health_lines():
    events, _ = run(commands.ping, HANDLERS["ping"][1])
    assert sent(events) == ["pong\nDatabase: ok\nOllama: ok"]


def test_ping_still_says_pong_when_the_api_is_down():
    events, _ = run(commands.ping, {"GET /health": httpx.ConnectError("refused")})
    assert sent(events) == ["pong\n" + client.NOT_ANSWERING]


# --- the registered commands ---


def _tree() -> AllowListTree:
    return build_tree(_client(), None, frozenset({EO}), discord.Object(42))


def _limits(command) -> dict:
    return {p.name: (p.required, p.min_value, p.max_value) for p in command.parameters}


def test_the_commands_are_guild_commands_only():
    tree = _tree()
    assert sorted(c.name for c in tree.get_commands(guild=discord.Object(42))) == [
        "archive",
        "ask",
        "delete",
        "list",
        "ping",
        "save",
    ]
    assert tree.get_commands() == []  # nothing global (DEVIATIONS 56)


def test_the_option_lengths():
    tree = _tree()
    guild = discord.Object(42)
    assert _limits(tree.get_command("ask", guild=guild)) == {"question": (True, 1, 1000)}
    save = tree.get_command("save", guild=guild)
    assert sorted(c.name for c in save.commands) == ["link", "text"]
    link, text = save.get_command("link"), save.get_command("text")
    assert _limits(link) == {
        "url": (True, 1, 2000),
        "title": (False, 1, 200),
        "replace": (False, None, None),
    }
    assert _limits(text) == {
        "title": (True, 1, 200),
        "text": (True, 1, 6000),
        "label": (False, 1, 200),
        "replace": (False, None, None),
    }


STRING, INTEGER, BOOLEAN = 3, 4, 5  # Discord option types


def _sent_options(name: str) -> list[dict]:
    """The options of one command exactly as `tree.sync` sends them to Discord (V152: a renamed
    option keeps its Python name in `parameters`, so tests read the payload instead)."""
    tree = _tree()
    command = tree.get_command(name, guild=discord.Object(42))
    keys = ("name", "type", "required", "choices", "min_value", "max_value")
    return [{k: o[k] for k in keys if k in o} for o in command.to_dict(tree)["options"]]


def test_list_sends_one_optional_status_choice():
    choices = [{"name": v, "value": v} for v in ("active", "archived", "all")]
    assert _sent_options("list") == [
        {"name": "status", "type": STRING, "required": False, "choices": choices}
    ]
    # Discord sends nothing for a left-out option, so the handler's default applies (U86)
    status = _tree().get_command("list", guild=discord.Object(42)).parameters[0]
    assert status.default == "active"


def test_archive_and_delete_send_a_required_id_and_delete_an_optional_confirm():
    document_id = {
        "name": "id",
        "type": INTEGER,
        "required": True,
        "min_value": 1,
        "max_value": 2**53 - 1,  # Discord's INTEGER limit (V151)
    }
    assert _sent_options("archive") == [document_id]
    assert _sent_options("delete") == [
        document_id,
        {"name": "confirm", "type": BOOLEAN, "required": False},
    ]
    confirm = _tree().get_command("delete", guild=discord.Object(42)).parameters[1]
    assert confirm.default is False


# --- /list, /archive, /delete (block o part 2) ---


def test_list_asks_for_active_documents_by_default_and_shows_the_lines():
    events, fake = run(commands.list_documents, {"GET /documents": ok([DOC])})
    assert fake.queries["GET /documents"] == {"status": "active"}
    assert sent(events) == ["7  2026-10-28  web  A saved page"]


@pytest.mark.parametrize("status", ["archived", "all"])
def test_list_sends_the_chosen_status(status):
    events, fake = run(commands.list_documents, {"GET /documents": ok([])}, status)
    assert fake.queries["GET /documents"] == {"status": status}
    assert sent(events) == [messages.NOTHING_LISTED[status]]


def test_list_of_20_shows_15_lines_and_the_cli_line_in_one_message():
    many = [DOC | {"document_id": n} for n in range(20, 0, -1)]
    events, _ = run(commands.list_documents, {"GET /documents": ok(many)})
    (text,) = sent(events)
    assert len(text.splitlines()) == 16
    assert text.endswith("Showing 15 of 20. Use the CLI list for all.")


def test_delete_without_confirm_asks_for_a_dry_run_and_shows_its_sentence():
    dry = (
        'Would delete document 7 "T" (text, 1 chunks). Nothing deleted.'
        " Send it again with confirm=true to delete it."
    )
    routes = {"DELETE /documents/7": ok({"deleted": False, "message": dry})}
    events, fake = run(commands.delete, routes, 7)
    assert fake.queries["DELETE /documents/7"] == {"confirm": "false"}
    assert sent(events) == [dry]


def test_delete_with_confirm_deletes_and_shows_the_export_warning():
    body = {
        "deleted": True,
        "message": 'Deleted document 7 "T" and its 1 chunks.',
        "export_warning": "Delete by hand: x.md.",
    }
    events, fake = run(commands.delete, {"DELETE /documents/7": ok(body)}, 7, True)
    assert fake.queries["DELETE /documents/7"] == {"confirm": "true"}
    assert sent(events) == ['Deleted document 7 "T" and its 1 chunks.\nDelete by hand: x.md.']


def test_delete_shows_the_api_not_found_sentence():
    routes = {"DELETE /documents/7": httpx.Response(404, json={"detail": "No document with id 7."})}
    events, _ = run(commands.delete, routes, 7, True)
    assert sent(events) == ["No document with id 7."]


def test_archive_posts_the_message_then_the_export_warning():
    body = {"title": "T", "message": 'Archived document 7 "T".', "export_warning": "Pending."}
    events, fake = run(commands.archive, {"POST /documents/7/archive": ok(body)}, 7)
    assert [e for e in events if e[0] == "request"] == [("request", "POST /documents/7/archive")]
    assert sent(events) == ['Archived document 7 "T".\nPending.']


def test_archive_refused_shows_the_api_sentence():
    detail = "Document 7 is archived; only active documents can be archived."
    routes = {"POST /documents/7/archive": httpx.Response(400, json={"detail": detail})}
    events, _ = run(commands.archive, routes, 7)
    assert sent(events) == [detail]


@pytest.mark.parametrize("name", ["list", "archive", "delete"])
def test_a_stranger_gets_nothing_from_the_new_commands(name):
    """FR40 through the real tree: the check runs before the command, so no defer and no
    request (the handler is never reached)."""
    events: list = []
    tree = AllowListTree(_client(), frozenset({EO}))
    allowed = asyncio.run(tree.interaction_check(FakeInteraction(events, STRANGER, name)))
    assert (allowed, events) == (False, [])


# --- the log (NFR8) ---


@pytest.mark.parametrize("name", HANDLERS)
def test_the_log_never_holds_the_question_text_link_or_key(name, caplog):
    caplog.set_level(logging.DEBUG, logger="agila.bot")
    handler, routes, args = HANDLERS[name]
    run(handler, routes, *args)
    assert f"command={name.replace('_', '-')}" in caplog.text
    for leak in (QUESTION, "secret saved text", "example.test", "test-key-not-a-secret", "http"):
        assert leak not in caplog.text


def test_list_archive_and_delete_log_no_title_or_id(caplog):
    caplog.set_level(logging.DEBUG, logger="agila.bot")
    secret = DOC | {"document_id": 987654, "title": "secret title words"}
    message = {"title": secret["title"], "message": 'Archived document 987654 "secret title".'}
    run(commands.list_documents, {"GET /documents": ok([secret])})
    run(commands.archive, {"POST /documents/987654/archive": ok(message)}, 987654)
    run(commands.delete, {"DELETE /documents/987654": ok(message | {"deleted": True})}, 987654)
    assert "command=list result=listed rows=1" in caplog.text
    assert "command=archive result=done" in caplog.text
    assert "command=delete result=done" in caplog.text
    assert "secret title" not in caplog.text
    assert "987654" not in caplog.text


def test_an_api_error_is_logged_as_its_class_only(caplog):
    caplog.set_level(logging.DEBUG, logger="agila.bot")
    routes = ask_routes(httpx.ReadTimeout(f"slow for {QUESTION}"))
    run(commands.ask, routes, QUESTION)
    assert "command=ask error=ReadTimeout" in caplog.text
    assert QUESTION not in caplog.text


@pytest.mark.parametrize("wrapped", [False, True])
def test_an_unexpected_error_is_logged_without_its_message(wrapped, caplog):
    caplog.set_level(logging.DEBUG, logger="agila.bot")
    tree = _tree()
    try:
        raise RuntimeError("leak-me")
    except RuntimeError as exc:
        error = exc
    if wrapped:
        error = app_commands.CommandInvokeError(
            tree.get_command("ask", guild=discord.Object(42)), error
        )
    asyncio.run(tree.on_error(FakeInteraction([], command="ask"), error))
    assert "command=ask error=RuntimeError at=test_bot_commands.py:" in caplog.text
    assert "leak-me" not in caplog.text
