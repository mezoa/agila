"""The slash commands (FR27) and who may use them (FR40).

Every command is a thin wrapper: defer first (Discord's 3-second rule), one or two API calls,
then the API's own text in pieces of at most 1,900 characters. The first message after the defer
replaces the "thinking..." state (`edit_original_response`, research V130); later pieces are
follow-ups. Every send passes `allowed_mentions` that parse nothing, so no reply can ping anyone.
The log gets one line per command: its name, the result or the error class, seconds and pieces;
never the question, the saved text, a link, a user ID or an error message (NFR8).
"""

import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path

import discord
from discord import app_commands

from agila.bot.client import AgilaApi, ApiError
from agila.bot.messages import ask_reply, ping_reply, save_reply, split

NO_PINGS = discord.AllowedMentions.none()
EMPTY = "Agila's API sent an empty reply."
log = logging.getLogger("agila.bot")


class AllowListTree(app_commands.CommandTree):
    """FR40: anyone not on the allow-list gets nothing at all, not even the "thinking..." state;
    discord.py sends no response when this check is False (research V127)."""

    def __init__(self, client: discord.Client, allowed: frozenset[int]):
        super().__init__(client)
        self.allowed = allowed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in self.allowed:
            return True
        log.info("ignored a request from a user not on the allow-list")
        return False

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Only the command, the error class and where it happened: an error's message can hold
        the question or a link."""
        original = getattr(error, "original", error)
        frames = traceback.extract_tb(original.__traceback__)
        where = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else "?"
        command = interaction.command.name if interaction.command else "?"
        log.error("command=%s error=%s at=%s", command, type(original).__name__, where)


async def _post(interaction: discord.Interaction, text: str, *, first: bool) -> int:
    """Send `text` in pieces, in order; the first piece replaces "thinking..." when `first`."""
    pieces = split(text) or [EMPTY]
    for n, piece in enumerate(pieces):
        if first and n == 0:
            await interaction.edit_original_response(content=piece, allowed_mentions=NO_PINGS)
        else:
            await interaction.followup.send(piece, allowed_mentions=NO_PINGS)
    return len(pieces)


def _done(command: str, started: float, pieces: int, result: str) -> None:
    seconds = time.perf_counter() - started
    log.info("command=%s %s seconds=%.1f pieces=%d", command, result, seconds, pieces)


async def ping(interaction: discord.Interaction, api: AgilaApi) -> None:
    """`pong`, then the database and Ollama lines from `/health` (Eo's Q8)."""
    started = time.perf_counter()
    await interaction.response.defer(thinking=True)
    try:
        health, result = await api.health(), "result=ok"
        text = ping_reply(health)
    except ApiError as exc:
        text, result = ping_reply(None, exc.sentence), f"error={exc.kind}"
    _done("ping", started, await _post(interaction, text, first=True), result)


async def ask(interaction: discord.Interaction, api: AgilaApi, question: str) -> None:
    """FR27: the passages first (no model call), then the answer as a second message. `/ask` is
    called even when nothing was found, so every question gets one `query_log` row (FR35)."""
    started = time.perf_counter()
    await interaction.response.defer(thinking=True)
    try:
        found = await api.search(question)
    except ApiError as exc:  # the API never saw the question, so there is nothing to log there
        _done(
            "ask", started, await _post(interaction, exc.sentence, first=True), f"error={exc.kind}"
        )
        return
    pieces = await _post(interaction, found["formatted"], first=True)
    try:
        answer = await api.ask(question)
        text, result = ask_reply(answer), f"result={answer['kind']}"
    except ApiError as exc:
        text, result = exc.sentence, f"error={exc.kind}"
    pieces += await _post(interaction, text, first=False)
    _done("ask", started, pieces, result)


async def _save(
    interaction: discord.Interaction, command: str, call: Callable[[], Awaitable[dict]]
) -> None:
    started = time.perf_counter()
    await interaction.response.defer(thinking=True)
    try:
        saved = await call()
        text, result = save_reply(saved), f"result={saved.get('outcome')}"
    except ApiError as exc:
        text, result = exc.sentence, f"error={exc.kind}"
    _done(command, started, await _post(interaction, text, first=True), result)


async def save_link(
    interaction: discord.Interaction,
    api: AgilaApi,
    url: str,
    title: str | None = None,
    replace: bool = False,
) -> None:
    await _save(interaction, "save-link", lambda: api.save_link(url, title, replace))


async def save_text(
    interaction: discord.Interaction,
    api: AgilaApi,
    title: str,
    text: str,
    label: str | None = None,
    replace: bool = False,
) -> None:
    await _save(interaction, "save-text", lambda: api.save_text(title, text, label, replace))


def build_tree(
    client: discord.Client, api: AgilaApi, allowed: frozenset[int], guild: discord.Object
) -> AllowListTree:
    """The four commands, registered for one server only (guild commands, DEVIATIONS 56)."""
    tree = AllowListTree(client, allowed)

    @app_commands.command(name="ping", description="Check that Agila and the laptop stack answer.")
    async def ping_command(interaction: discord.Interaction) -> None:
        await ping(interaction, api)

    @app_commands.command(name="ask", description="Ask a question about your saved material.")
    @app_commands.describe(question="Your question")
    async def ask_command(
        interaction: discord.Interaction, question: app_commands.Range[str, 1, 1000]
    ) -> None:
        await ask(interaction, api, question)

    save = app_commands.Group(name="save", description="Save a link or pasted text in Agila.")

    @save.command(name="link", description="Save a web page.")
    @app_commands.describe(
        url="The link", title="A title (default: the page's own)", replace="Supersede older copies"
    )
    async def save_link_command(
        interaction: discord.Interaction,
        url: app_commands.Range[str, 1, 2000],
        title: app_commands.Range[str, 1, 200] | None = None,
        replace: bool = False,
    ) -> None:
        await save_link(interaction, api, url, title, replace)

    @save.command(name="text", description="Save pasted text (up to 6,000 characters).")
    @app_commands.describe(
        title="A title",
        text="The text to save",
        label="A source label (default: the title)",
        replace="Supersede the note with the same label",
    )
    async def save_text_command(
        interaction: discord.Interaction,
        title: app_commands.Range[str, 1, 200],
        text: app_commands.Range[str, 1, 6000],
        label: app_commands.Range[str, 1, 200] | None = None,
        replace: bool = False,
    ) -> None:
        await save_text(interaction, api, title, text, label, replace)

    for command in (ping_command, ask_command, save):
        tree.add_command(command, guild=guild)
    return tree
