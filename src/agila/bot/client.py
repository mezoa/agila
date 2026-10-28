"""The bot's only door to Agila: the API on 127.0.0.1:8000 (NFR10).

Every request carries the API key and `X-Agila-Channel: discord`, so `query_log` says `discord`
(DEVIATIONS 54). Every failure becomes one `ApiError`: a sentence for Discord and a short `kind`
(the error class or `HTTP <code>`), which is the only part the bot logs. Neither ever holds the
URL, the question or the key (NFR8). Async, so a long answer never blocks the Discord connection.
"""

import httpx

BASE_URL = "http://127.0.0.1:8000"
CHANNEL = "discord"
CONNECT_SECONDS = 5.0
ASK_SECONDS = 270.0  # two model calls of at most 120 s each (llm.TIMEOUT_SECONDS), plus search
SAVE_SECONDS = 120.0  # a download of up to 15 s plus embedding (Eo's Q5, research U80)
OTHER_SECONDS = 30.0
NOT_ANSWERING = (
    "Agila's API is not answering at 127.0.0.1:8000; is the stack running on the laptop?"
)
WRONG_KEY = "The bot's API key was refused; check AGILA_API_KEY."
UNREADABLE = "Agila's API sent a reply the bot could not read."
SAVE_MAY_FINISH = " The save may still finish; check before saving again."


class ApiError(Exception):
    """One sentence to show in Discord, and `kind` for the log."""

    def __init__(self, sentence: str, kind: str):
        super().__init__(sentence)
        self.sentence = sentence
        self.kind = kind


class AgilaApi:
    def __init__(self, key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-API-Key": key, "X-Agila-Channel": CHANNEL},
            transport=transport,
            trust_env=False,  # never through a proxy from the environment, like llm.py
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict:
        """`/health` (no key needed); a 503 still has the body naming what is down."""
        return await self._call("GET", "/health", OTHER_SECONDS, ok=(200, 503))

    async def search(self, question: str) -> dict:
        """Up to 3 passages and their `formatted` text; no model call, no log row (FR10)."""
        return await self._call("GET", "/search", OTHER_SECONDS, params={"question": question})

    async def ask(self, question: str) -> dict:
        return await self._call("POST", "/ask", ASK_SECONDS, json={"question": question})

    async def save_link(self, url: str, title: str | None = None, replace: bool = False) -> dict:
        body = {"url": url, "title": title, "replace": replace}
        return await self._call("POST", "/save/url", SAVE_SECONDS, save=True, json=body)

    async def save_text(
        self, title: str, text: str, label: str | None = None, replace: bool = False
    ) -> dict:
        """FR1 needs a label; left out, it is the title (Eo's Q4)."""
        body = {"title": title, "label": label or title, "text": text, "replace": replace}
        return await self._call("POST", "/save/text", SAVE_SECONDS, save=True, json=body)

    async def list_documents(self, status: str = "active") -> list[dict]:
        """The documents with that status (`active`, `archived` or `all`), newest first."""
        return await self._call("GET", "/documents", OTHER_SECONDS, params={"status": status})

    async def archive(self, document_id: int) -> dict:
        return await self._call("POST", f"/documents/{document_id}/archive", OTHER_SECONDS)

    async def delete(self, document_id: int, confirm: bool = False) -> dict:
        """Without `confirm` the API deletes nothing and says what would go (FR20)."""
        params = {"confirm": "true" if confirm else "false"}
        return await self._call("DELETE", f"/documents/{document_id}", OTHER_SECONDS, params=params)

    async def _call(
        self,
        method: str,
        path: str,
        seconds: float,
        *,
        ok: tuple[int, ...] = (200,),
        save: bool = False,
        **kwargs,
    ) -> dict | list:
        timeout = httpx.Timeout(seconds, connect=CONNECT_SECONDS)
        try:
            response = await self._client.request(method, path, timeout=timeout, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ApiError(NOT_ANSWERING, type(exc).__name__) from None
        except httpx.TimeoutException as exc:
            sentence = f"Agila's API took longer than {seconds:g} seconds to reply."
            raise ApiError(
                sentence + (SAVE_MAY_FINISH if save else ""), type(exc).__name__
            ) from None
        except httpx.HTTPError as exc:
            raise ApiError(NOT_ANSWERING, type(exc).__name__) from None
        if response.status_code not in ok:
            raise ApiError(_refusal(response), f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise ApiError(UNREADABLE, "ValueError") from None


def _refusal(response: httpx.Response) -> str:
    """The API's own one-sentence `detail` for 400, 404 and 503; a fixed sentence otherwise."""
    if response.status_code == 401:
        return WRONG_KEY
    if response.status_code in (400, 404, 503):
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, str) and detail:
            return detail
    return f"Agila's API answered with HTTP {response.status_code}."
