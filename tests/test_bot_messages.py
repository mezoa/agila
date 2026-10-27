"""Block o step 4: the bot's pure text helpers (no Discord, no network, no API)."""

import pytest

from agila.bot import messages
from agila.bot.messages import allowed_ids, ask_reply, ping_reply, save_reply, split

# --- the allow-list (FR40) ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1, 22,333", {1, 22, 333}),
        ("123456789012345678", {123456789012345678}),
        ("1,,2", {1, 2}),
        (" 7 ,", {7}),
        ("", set()),
        ("   ", set()),
        (None, set()),
    ],
)
def test_allowed_ids_reads_comma_separated_numbers_and_blank_means_nobody(text, expected):
    assert allowed_ids(text) == frozenset(expected)


@pytest.mark.parametrize("bad", ["12a", "-5", "1.5", "1;2", "١٢"])
def test_a_bad_entry_names_the_variable_never_the_value(bad):
    with pytest.raises(ValueError) as caught:
        allowed_ids(f"42,{bad}")
    assert str(caught.value) == "DISCORD_ALLOWED_USER_IDS must be comma-separated numbers."
    assert bad not in str(caught.value)


# --- splitting (FR27, DEVIATIONS 57) ---


def _check(text, pieces):
    """Every piece fits, none is empty, and no visible character is lost or reordered."""
    assert all(0 < len(p) <= messages.LIMIT for p in pieces)
    assert all(p.strip() == p for p in pieces)
    assert "".join("".join(pieces).split()) == "".join(text.split())


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n", "\r\n \r\n"])
def test_empty_or_blank_text_gives_no_piece(text):
    assert split(text) == []


def test_text_up_to_the_limit_is_one_piece():
    assert messages.LIMIT == 1900
    assert split("a" * 1900) == ["a" * 1900]


def test_one_character_over_the_limit_without_any_break_is_cut_hard():
    assert split("a" * 1901) == ["a" * 1900, "a"]


def test_a_blank_line_is_the_first_choice():
    text = "x" * 500 + "\n\n" + "y" * 500 + "\n" + "z" * 1000  # 2,003 characters
    pieces = split(text)
    assert pieces == ["x" * 500, "y" * 500 + "\n" + "z" * 1000]
    _check(text, pieces)


def test_without_a_blank_line_the_last_line_break():
    text = "x" * 1000 + "\n" + "y" * 1000
    assert split(text) == ["x" * 1000, "y" * 1000]


@pytest.mark.parametrize("end", [".", "?", "!"])
def test_without_a_line_break_the_last_sentence_end(end):
    text = "a" * 1000 + end + " " + "b" * 500 + " " + "c" * 600  # 2,103 characters
    pieces = split(text)
    assert pieces == ["a" * 1000 + end, "b" * 500 + " " + "c" * 600]
    _check(text, pieces)


def test_without_a_sentence_end_the_last_space():
    text = "a" * 1000 + " " + "b" * 1000
    assert split(text) == ["a" * 1000, "b" * 1000]


def test_one_long_word_is_cut_hard_every_1900_characters():
    text = "h" * 5000  # a very long link, for example
    assert [len(p) for p in split(text)] == [1900, 1900, 1200]


def test_blank_lines_at_the_start_give_no_empty_piece():
    text = "\n\n" + "a" * 1000 + "\n\n" + "b" * 1000
    assert split(text) == ["a" * 1000, "b" * 1000]


def test_crlf_line_breaks_are_never_cut_in_half():
    pieces = split("x" * 1000 + "\r\n" + "y" * 1000)
    assert pieces == ["x" * 1000, "y" * 1000]
    assert not any("\r" in p for p in pieces)


def test_an_emoji_at_the_cut_stays_whole():
    text = "a" * 1899 + "\N{GRINNING FACE}" + "b" * 100
    assert split(text) == ["a" * 1899 + "\N{GRINNING FACE}", "b" * 100]


def test_many_short_paragraphs_fill_each_piece():
    text = "Para text here.\n\n" * 300  # 5,100 characters
    pieces = split(text)
    assert len(pieces) == 3
    assert all(len(p) > 1800 for p in pieces[:-1])
    _check(text, pieces)


def test_every_case_keeps_every_character_in_order():
    for text in [
        "a" * 1901,
        "h" * 5000,
        "x" * 1000 + "\n" + "y" * 1000,
        "One. Two? Three! " * 400,
        "word " * 2000,
        ("\N{GRINNING FACE} " * 1500),
    ]:
        _check(text, split(text))


# --- reply wording (only fields the API returns) ---


def test_ask_reply_shows_the_answer_with_its_sources():
    answer = {
        "kind": "answer",
        "text": "It says so.",
        "note": None,
        "formatted": 'It says so.\n\nSources:\n1. "Quote."',
    }
    assert ask_reply(answer) == answer["formatted"]


def test_ask_reply_shows_a_refusal_sentence():
    refusal = {
        "kind": "refusal",
        "text": "I couldn't find this in your saved material.",
        "note": None,
        "formatted": "I couldn't find this in your saved material.",
    }
    assert ask_reply(refusal) == "I couldn't find this in your saved material."


@pytest.mark.parametrize("kind", ["passages", "busy"])
def test_ask_reply_shows_only_the_note_for_the_fallback_and_busy(kind):
    note = "Agila is answering another question right now. Try again in a minute."
    reply = {
        "kind": kind,
        "text": "",
        "note": note,
        "formatted": note + "\n\nClosest passages:\n1. Title (source)",
    }
    assert ask_reply(reply) == note


@pytest.mark.parametrize(
    "message",
    [
        "Saved Bot check: 1 chunks",
        "Already saved, unchanged: Bot check (document 12).",
        "Saved Bot check: 1 chunks. It replaces document 12, now superseded.",
    ],
    ids=["saved", "unchanged", "replaced"],
)
def test_save_reply_is_the_api_message(message):
    assert save_reply({"message": message, "warning": None, "export_warning": None}) == message


def test_save_reply_adds_each_warning_on_its_own_line():
    saved = {
        "message": "Saved Note: 1 chunks",
        "warning": 'Warning: a different note labelled L is already saved as document 3 "Old".',
        "export_warning": "The Obsidian note could not be written (OSError); run export --retry.",
    }
    assert save_reply(saved).splitlines() == [
        saved["message"],
        saved["warning"],
        saved["export_warning"],
    ]


def test_ping_reply_adds_the_health_lines():
    assert ping_reply({"database": "ok", "ollama": "ok"}) == "pong\nDatabase: ok\nOllama: ok"


def test_ping_reply_shows_the_api_sentence_when_something_is_down():
    health = {"database": "ok", "ollama": "Ollama is not running on the laptop."}
    assert ping_reply(health).splitlines()[2] == "Ollama: Ollama is not running on the laptop."


def test_ping_still_says_pong_when_the_api_does_not_answer():
    problem = "Agila's API is not answering at 127.0.0.1:8000; is the stack running on the laptop?"
    assert ping_reply(None, problem) == "pong\n" + problem
    assert ping_reply(None) == "pong"


def test_the_allow_list_sentence_is_at_most_25_words():
    with pytest.raises(ValueError) as caught:
        allowed_ids("x")
    assert len(str(caught.value).split()) <= 25  # NFR7
