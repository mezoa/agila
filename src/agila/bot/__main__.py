"""Start the Discord bot (FR27), or register its commands once with `--sync`.

    uv run --env-file .env python -m agila.bot           (own window; Ctrl+C stops it)
    uv run --env-file .env python -m agila.bot --sync    (once, and again when commands change)

Settings come only from the environment: DISCORD_BOT_TOKEN, DISCORD_ALLOWED_USER_IDS,
DISCORD_GUILD_ID and AGILA_API_KEY; then SAVE_VIA_N8N (on only for exactly `true`, block t) and
AGILA_N8N_SAVE_KEY, required when it is on. A missing or bad one is one sentence naming the
variable, never its value. The log goes to `logs/bot.log` at INFO (never DEBUG, where discord.py
writes whole payloads); httpx is kept at WARNING because it logs every request URL (research V135).
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

import discord
from discord import app_commands

from agila.bot.client import AgilaApi
from agila.bot.commands import NO_PINGS, build_tree
from agila.bot.messages import ALLOWED_VARIABLE, allowed_ids

TOKEN_VARIABLE = "DISCORD_BOT_TOKEN"
GUILD_VARIABLE = "DISCORD_GUILD_ID"
KEY_VARIABLE = "AGILA_API_KEY"
VIA_N8N_VARIABLE = "SAVE_VIA_N8N"
SAVE_KEY_VARIABLE = "AGILA_N8N_SAVE_KEY"
LOG_FILE = Path(__file__).resolve().parents[3] / "logs" / "bot.log"
QUIET_LOGGERS = ("httpx", "httpcore")
START = "uv run --env-file .env python -m agila.bot"
ONLINE = "Agila bot is online. Log: logs\\bot.log. Stop with Ctrl+C."
NOBODY = f"{ALLOWED_VARIABLE} is empty, so the bot answers nobody."
BAD_TOKEN = f"Discord refused the token in {TOKEN_VARIABLE}."
VIA_N8N = f"Saves go through n8n ({VIA_N8N_VARIABLE}=true)."


class SettingsError(Exception):
    pass


class AgilaBot(discord.Client):
    """The client: default intents only (no privileged one, research V128), no pings by default,
    and the allow-listed command tree for one server."""

    def __init__(self, api: AgilaApi, allowed: frozenset[int], guild_id: int, sync: bool = False):
        super().__init__(intents=discord.Intents.default(), allowed_mentions=NO_PINGS)
        self.api = api
        self.guild = discord.Object(guild_id)
        self.sync_only = sync
        self.tree = build_tree(self, api, allowed, self.guild)
        self._announced = False
        self._api_closed = False

    async def setup_hook(self) -> None:
        # Runs after login, so the application id that `sync` needs is known (research 2r).
        await register(self.tree, self.guild, self.sync_only, self.close)

    async def on_ready(self) -> None:
        if not self._announced:  # on_ready comes again after every reconnect
            self._announced = True
            print(ONLINE, flush=True)

    async def close(self) -> None:
        if not self._api_closed:
            self._api_closed = True
            await self.api.aclose()
        await super().close()


async def register(
    tree: app_commands.CommandTree,
    guild: discord.Object,
    sync: bool,
    close: Callable[[], object],
) -> None:
    """With `--sync`: register the commands in the one server, say how many, and stop. A normal
    start never syncs (DEVIATIONS 56)."""
    if not sync:
        return
    registered = await tree.sync(guild=guild)
    print(f"Registered {len(registered)} commands in the server.", flush=True)
    await close()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"Missing environment variable {name}. Add it to .env and run: {START}")
    return value


def settings() -> tuple[str, frozenset[int], int, str]:
    """Token, allow-list, server id and API key, in that order of checking."""
    token = _required(TOKEN_VARIABLE)
    if ALLOWED_VARIABLE not in os.environ:  # present but blank is allowed: nobody (FR40)
        raise SettingsError(f"Missing environment variable {ALLOWED_VARIABLE}. Add it to .env.")
    try:
        allowed = allowed_ids(os.environ[ALLOWED_VARIABLE])
    except ValueError as exc:
        raise SettingsError(str(exc)) from None
    guild = _required(GUILD_VARIABLE)
    if not (guild.isascii() and guild.isdigit()):
        raise SettingsError(f"{GUILD_VARIABLE} must be a number.")
    return token, allowed, int(guild), _required(KEY_VARIABLE)


def save_key() -> str | None:
    """The n8n save key when SAVE_VIA_N8N is exactly `true` (then it is required), else None."""
    if os.environ.get(VIA_N8N_VARIABLE) != "true":
        return None
    return _required(SAVE_KEY_VARIABLE)


def _run(bot: AgilaBot, token: str, **kwargs) -> None:
    bot.run(token, **kwargs)


def main(argv: list[str] | None = None, run: Callable[..., None] = _run) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agila.bot", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--sync", action="store_true", help="register the commands in the server, then stop"
    )
    args = parser.parse_args(argv)
    try:
        token, allowed, guild_id, key = settings()
        n8n_key = save_key()
    except SettingsError as exc:
        print(exc)
        return 1
    if not allowed:
        print(NOBODY)
    if n8n_key:
        print(VIA_N8N)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    bot = AgilaBot(AgilaApi(key, save_key=n8n_key), allowed, guild_id, sync=args.sync)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    try:
        run(bot, token, log_handler=handler, log_level=logging.INFO, root_logger=True)
    except discord.LoginFailure:
        print(BAD_TOKEN)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
