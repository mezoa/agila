"""The bot's only door to Agila: the API on 127.0.0.1:8000 (NFR10).

Every request carries the API key and `X-Agila-Channel: discord`, so `query_log` says `discord`
(DEVIATIONS 54). Every failure becomes one `ApiError`: a sentence for Discord and a short `kind`
(the error class or `HTTP <code>`), which is the only part the bot logs. Neither ever holds the
URL, the question or the key (NFR8). Async, so a long answer never blocks the Discord connection.

With a save key (SAVE_VIA_N8N=true, block t), `/save` goes to n8n's `agila-save` webhook instead
(Workflow A) through a second client that carries only `X-Agila-Save-Key`, so the API key never
lands in n8n's run data. There is no fallback to the API: a failure is one sentence.
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
N8N_SAVE_URL = "http://127.0.0.1:5678/webhook/agila-save"
SAVE_KEY_HEADER = "X-Agila-Save-Key"
N8N_SECONDS = 30.0
N8N_SENT = "Sent to the save pipeline; the result is posted by n8n in #agila-digest."
N8N_DOWN = (
    "n8n is not answering at 127.0.0.1:5678; nothing was saved."
    " Start n8n or set SAVE_VIA_N8N=false."
)
N8N_NOT_PUBLISHED = (
    "The n8n save workflow is not published; nothing was saved. Publish agila-save in n8n."
)
N8N_KEY_REFUSED = "n8n refused the bot's save key; nothing was saved. Check AGILA_N8N_SAVE_KEY."
N8N_TIMEOUT = (
    "n8n did not confirm within 30 seconds; the save may still run."
    " Check #agila-digest before saving again."
)
N8N_OTHER = "n8n answered with HTTP {code}; check #agila-digest before saving again."


class ApiError(Exception):
    """One sentence to show in Discord, and `kind` for the log."""

    def __init__(self, sentence: str, kind: str):
        super().__init__(sentence)
        self.sentence = sentence
        self.kind = kind


class AgilaApi:
    def __init__(
        self,
        key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        save_key: str | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-API-Key": key, "X-Agila-Channel": CHANNEL},
            transport=transport,
            trust_env=False,  # never through a proxy from the environment, like llm.py
        )
        self.save_key = save_key
        self._n8n = None
        if save_key:
            self._n8n = httpx.AsyncClient(
                headers={SAVE_KEY_HEADER: save_key},  # only this header, never the API key
                transport=transport,
                trust_env=False,
            )

    async def aclose(self) -> None:
        await self._client.aclose()
        if self._n8n is not None:
            await self._n8n.aclose()

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
        if self._n8n is not None:
            return await self._send_to_n8n("url", body)
        return await self._call("POST", "/save/url", SAVE_SECONDS, save=True, json=body)

    async def save_text(
        self, title: str, text: str, label: str | None = None, replace: bool = False
    ) -> dict:
        """FR1 needs a label; left out, it is the title (Eo's Q4)."""
        body = {"title": title, "label": label or title, "text": text, "replace": replace}
        if self._n8n is not None:
            return await self._send_to_n8n("text", body)
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

    async def _send_to_n8n(self, kind: str, save: dict) -> dict:
        """Hand the save to n8n, which posts the result in #agila-digest. The reply has the API's
        shape, so `save_reply` and the `_save` log line need no change."""
        timeout = httpx.Timeout(N8N_SECONDS, connect=CONNECT_SECONDS)
        try:
            response = await self._n8n.post(
                N8N_SAVE_URL, json={"kind": kind, "save": save}, timeout=timeout
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ApiError(N8N_DOWN, type(exc).__name__) from None
        except httpx.TimeoutException as exc:
            raise ApiError(N8N_TIMEOUT, type(exc).__name__) from None
        except httpx.HTTPError as exc:
            raise ApiError(N8N_DOWN, type(exc).__name__) from None
        code = response.status_code
        if code == 200:
            return {"message": N8N_SENT, "outcome": "sent-to-n8n"}
        sentence = {404: N8N_NOT_PUBLISHED, 403: N8N_KEY_REFUSED}.get(code)
        raise ApiError(sentence or N8N_OTHER.format(code=code), f"HTTP {code}")

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
