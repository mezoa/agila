"""Block o step 7: starting the bot, `--sync`, the log and the bot's structure (no Discord: `run`
is replaced by a recorder; the token is the placeholder string, never a real one)."""

import ast
import asyncio
import logging
import sys
from pathlib import Path

import discord
import pytest
from botfakes import EO

from agila.bot import __main__ as start

PROJECT = Path(__file__).resolve().parents[1]
BOT_DIR = PROJECT / "src" / "agila" / "bot"
TOKEN = "placeholder"
GOOD = {
    "DISCORD_BOT_TOKEN": TOKEN,
    "DISCORD_ALLOWED_USER_IDS": str(EO),
    "DISCORD_GUILD_ID": "42",
    "AGILA_API_KEY": "test-key-not-a-secret",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Good settings and a log file in a temporary folder (never the real `logs/`)."""
    for name, value in GOOD.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(start, "LOG_FILE", tmp_path / "logs" / "bot.log")
    levels = {name: logging.getLogger(name).level for name in start.QUIET_LOGGERS}
    yield monkeypatch
    for name, level in levels.items():  # main changes these levels; put them back
        logging.getLogger(name).setLevel(level)


class Recorder:
    """Stands in for `bot.run`: keeps what main passed, closes the log file, opens no socket."""

    def __init__(self, raises: Exception | None = None):
        self.calls: list = []
        self.raises = raises

    def __call__(self, bot, token, **kwargs):
        self.calls.append((bot, token, kwargs))
        kwargs["log_handler"].close()
        asyncio.run(bot.api.aclose())
        if self.raises:
            raise self.raises


def _never(*args, **kwargs):
    pytest.fail("the bot must not start")


# --- settings: one sentence naming the variable, never its value ---


@pytest.mark.parametrize("name", list(GOOD))
def test_a_missing_variable_is_one_sentence_naming_it(env, capsys, name):
    env.delenv(name)
    assert start.main([], run=_never) == 1
    out = capsys.readouterr().out
    assert out.startswith(f"Missing environment variable {name}.")
    assert out.count("\n") == 1


@pytest.mark.parametrize("name", ["DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "AGILA_API_KEY"])
def test_a_blank_required_variable_counts_as_missing(env, capsys, name):
    env.setenv(name, "   ")
    assert start.main([], run=_never) == 1
    assert capsys.readouterr().out.startswith(f"Missing environment variable {name}.")


def test_a_bad_allow_list_names_the_variable_not_the_value(env, capsys):
    env.setenv("DISCORD_ALLOWED_USER_IDS", "abc")
    assert start.main([], run=_never) == 1
    out = capsys.readouterr().out
    assert out == "DISCORD_ALLOWED_USER_IDS must be comma-separated numbers.\n"


@pytest.mark.parametrize("value", ["x", "12.5", "-3"])
def test_a_bad_server_id_is_one_sentence(env, capsys, value):
    env.setenv("DISCORD_GUILD_ID", value)
    assert start.main([], run=_never) == 1
    assert capsys.readouterr().out == "DISCORD_GUILD_ID must be a number.\n"


def test_a_blank_allow_list_starts_but_says_it_answers_nobody(env, capsys):
    env.setenv("DISCORD_ALLOWED_USER_IDS", "")
    recorder = Recorder()
    assert start.main([], run=recorder) == 0
    assert capsys.readouterr().out == start.NOBODY + "\n"
    assert recorder.calls[0][0].tree.allowed == frozenset()


# --- a good start ---


def test_a_good_start_runs_the_bot_once_with_the_token_and_the_log_file(env, capsys, caplog):
    recorder = Recorder()
    assert start.main([], run=recorder) == 0
    ((bot, token, kwargs),) = recorder.calls
    assert token == TOKEN
    assert isinstance(kwargs["log_handler"], logging.FileHandler)
    assert Path(kwargs["log_handler"].baseFilename) == start.LOG_FILE
    assert (kwargs["log_level"], kwargs["root_logger"]) == (logging.INFO, True)
    assert start.LOG_FILE.parent.is_dir()
    assert bot.sync_only is False
    assert bot.tree.allowed == frozenset({EO})
    assert bot.guild.id == 42
    # nothing printed or logged holds the token
    assert TOKEN not in capsys.readouterr().out
    assert TOKEN not in caplog.text


def test_httpx_is_kept_at_warning_because_it_logs_request_urls(env):
    assert start.main([], run=Recorder()) == 0
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING


def test_the_client_pings_nobody_and_asks_for_no_privileged_intent(env):
    recorder = Recorder()
    start.main([], run=recorder)
    bot = recorder.calls[0][0]
    assert bot.allowed_mentions.to_dict() == {"parse": []}
    assert bot.intents == discord.Intents.default()
    assert not (bot.intents.message_content or bot.intents.members or bot.intents.presences)


def test_sync_is_passed_to_the_bot(env):
    recorder = Recorder()
    assert start.main(["--sync"], run=recorder) == 0
    assert recorder.calls[0][0].sync_only is True


def test_a_refused_token_is_one_sentence(env, capsys):
    failure = discord.LoginFailure("Improper token has been passed.")
    assert start.main([], run=Recorder(raises=failure)) == 1
    assert capsys.readouterr().out == "Discord refused the token in DISCORD_BOT_TOKEN.\n"


# --- registering the commands (--sync only) ---


class FakeTree:
    def __init__(self):
        self.synced: list = []

    async def sync(self, *, guild):
        self.synced.append(guild.id)
        return ["ping", "ask", "save"]


def test_a_normal_start_never_syncs():
    tree, closed = FakeTree(), []

    async def close():
        closed.append(True)

    asyncio.run(start.register(tree, discord.Object(42), False, close))
    assert (tree.synced, closed) == ([], [])


def test_sync_registers_in_the_one_server_says_how_many_and_stops(capsys):
    tree, closed = FakeTree(), []

    async def close():
        closed.append(True)

    asyncio.run(start.register(tree, discord.Object(42), True, close))
    assert (tree.synced, closed) == ([42], [True])
    assert capsys.readouterr().out == "Registered 3 commands in the server.\n"


def test_online_is_printed_once_even_after_a_reconnect(env, capsys):
    recorder = Recorder()
    start.main([], run=recorder)
    bot = recorder.calls[0][0]
    asyncio.run(bot.on_ready())
    asyncio.run(bot.on_ready())
    assert capsys.readouterr().out == start.ONLINE + "\n"


def test_closing_the_bot_closes_the_api_client_once():
    closed = []

    class FakeApi:
        async def aclose(self):
            closed.append(True)

    async def go():
        bot = start.AgilaBot(FakeApi(), frozenset({EO}), 42)
        await bot.close()
        await bot.close()

    asyncio.run(go())
    assert closed == [True]


# --- structure: a thin client that never touches the vault (NFR10, D7) ---


def _bot_files() -> list[Path]:
    files = sorted(BOT_DIR.glob("*.py"))
    assert {f.name for f in files} == {
        "__init__.py",
        "__main__.py",
        "client.py",
        "commands.py",
        "messages.py",
    }
    return files


def test_the_bot_imports_only_the_standard_library_discord_httpx_and_itself():
    allowed = set(sys.stdlib_module_names) | {"discord", "httpx"}
    for path in _bot_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                assert name.startswith("agila.bot") or top in allowed, f"{path.name}: {name}"


def test_the_bot_opens_no_file_itself():
    forbidden = {"open", "read_text", "write_text", "read_bytes", "write_bytes", "unlink"}
    for path in _bot_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                assert name not in forbidden, f"{path.name}:{node.lineno} calls {name}"


# --- the files that hold names, never values ---


def test_env_example_lists_the_three_discord_names_with_empty_values():
    lines = (PROJECT / ".env.example").read_text(encoding="utf-8").splitlines()
    for name in ("DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_USER_IDS", "DISCORD_GUILD_ID"):
        assert f"{name}=" in lines


def test_the_log_folder_is_kept_out_of_git_and_the_image():
    assert "logs/" in (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "logs" in (PROJECT / ".dockerignore").read_text(encoding="utf-8").splitlines()
