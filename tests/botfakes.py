"""Fakes for the bot tests: a Discord interaction and the Agila API, both writing to one shared
`events` list, so a test can check the order of defer, requests and messages. No Discord, no
network: the API is an `httpx.MockTransport`."""

import asyncio
from types import SimpleNamespace

import httpx

from agila.bot.client import AgilaApi

KEY = "test-key-not-a-secret"
EO = 111111111111111111  # a made-up Discord user ID, the only one on the test allow-list
STRANGER = 222222222222222222


class FakeResponse:
    def __init__(self, events: list):
        self.events = events

    async def defer(self, **kwargs):
        self.events.append(("defer", kwargs))


class FakeFollowup:
    def __init__(self, events: list):
        self.events = events

    async def send(self, content, **kwargs):
        self.events.append(("followup", {"content": content, **kwargs}))


class FakeInteraction:
    """The parts of `discord.Interaction` the commands use."""

    def __init__(self, events: list, user_id: int = EO, command: str | None = None):
        self.events = events
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeResponse(events)
        self.followup = FakeFollowup(events)
        self.command = SimpleNamespace(name=command) if command else None

    async def edit_original_response(self, **kwargs):
        self.events.append(("edit", kwargs))


class FakeApi:
    """Answers by route ("GET /search" -> a Response, or an exception to raise)."""

    def __init__(self, events: list, routes: dict):
        self.events = events
        self.routes = routes
        self.bodies: dict[str, bytes] = {}
        self.queries: dict[str, dict[str, str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        route = f"{request.method} {request.url.path}"
        self.events.append(("request", route))
        self.bodies[route] = request.content
        self.queries[route] = dict(request.url.params)
        answer = self.routes[route]
        if isinstance(answer, Exception):
            raise answer
        return answer


def run(handler, routes: dict, *args, user_id: int = EO) -> tuple[list, FakeApi]:
    """Run one command handler against the fakes; return the events and the fake API."""
    events: list = []
    fake = FakeApi(events, routes)

    async def go():
        api = AgilaApi(KEY, transport=httpx.MockTransport(fake))
        try:
            await handler(FakeInteraction(events, user_id), api, *args)
        finally:
            await api.aclose()

    asyncio.run(go())
    return events, fake


def sent(events: list) -> list[str]:
    """The texts the user saw, in order (edits and follow-ups)."""
    return [e[1]["content"] for e in events if e[0] in ("edit", "followup")]
