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

from agila.bot import client, commands
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
        "ask",
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


# --- the log (NFR8) ---


@pytest.mark.parametrize("name", HANDLERS)
def test_the_log_never_holds_the_question_text_link_or_key(name, caplog):
    caplog.set_level(logging.DEBUG, logger="agila.bot")
    handler, routes, args = HANDLERS[name]
    run(handler, routes, *args)
    assert f"command={name.replace('_', '-')}" in caplog.text
    for leak in (QUESTION, "secret saved text", "example.test", "test-key-not-a-secret", "http"):
        assert leak not in caplog.text


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
