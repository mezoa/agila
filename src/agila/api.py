"""The web API (FR26): save, ask, search, list, archive and delete behind a key; `/health` and
`/docs` open.

    uv run --env-file .env python -m agila.api      (serves http://127.0.0.1:8000, /docs)

The key is read from `AGILA_API_KEY` and sent in the `X-API-Key` header; a missing, empty or wrong
key gets one 401 sentence (V72). Every route and our own dependencies are plain `def`, so FastAPI
runs them in worker threads: a second ask gets the busy sentence at once and `/health` keeps
answering during a long ask (V73). No search, answer or model logic lives here: the routes call
`questions`, `retrieval` and `library`, and only `llm.py` talks to Ollama.
"""

import os
import secrets
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import ModuleType
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from agila import db, llm
from agila.ask import Model, format_answer, format_search
from agila.embed import Embedder
from agila.export import local_date
from agila.library import (
    LibraryError,
    NotFound,
    SaveError,
    archive,
    delete_document,
    describe,
    document_info,
    list_documents,
    save_text,
    save_url,
)
from agila.questions import CHANNELS, ask_question
from agila.retrieval import MIN_SIMILARITY, search
from agila.stale import LIMIT as STALE_LIMIT
from agila.stale import find_stale, format_stale

HOST = "127.0.0.1"  # FR26; the default when AGILA_HOST is unset
HOST_VARIABLE = "AGILA_HOST"  # the container sets 0.0.0.0; Compose publishes only 127.0.0.1:8000
PORT = 8000
KEY_HEADER = "X-API-Key"
KEY_VARIABLE = "AGILA_API_KEY"
WRONG_KEY = "Missing or wrong API key."
LAPTOP_ONLY = "include_private=true is allowed only from the laptop."  # Eo's Q8
CHANNEL_HEADER = "X-Agila-Channel"  # who is asking, for query_log (DEVIATIONS 54)
API_CHANNELS = ("web", "discord", "n8n")  # `cli` is written only by the CLI, never over HTTP


class AskIn(BaseModel):
    question: str


class TextIn(BaseModel):
    title: str
    label: str
    text: str
    replace: bool = False


class UrlIn(BaseModel):
    url: str
    title: str | None = None
    replace: bool = False


def connection() -> Iterator[psycopg.Connection]:
    """One connection per request; a database that is down is one 503 sentence."""
    try:
        conn = db.connect()
    except RuntimeError as exc:  # a missing POSTGRES_* variable, named without its value
        raise HTTPException(503, f"{exc}, so the database cannot be reached.") from None
    except psycopg.OperationalError:
        raise HTTPException(503, db.DATABASE_DOWN) from None
    with conn:
        yield conn


Conn = Annotated[psycopg.Connection, Depends(connection)]


def channel(value: Annotated[str | None, Header(alias=CHANNEL_HEADER)] = None) -> str:
    """The `X-Agila-Channel` header: missing means `web`; anything not in API_CHANNELS is 400."""
    if value is None:
        return "web"
    if value not in API_CHANNELS:
        raise HTTPException(400, f'Unknown channel "{value}"; use web, discord or n8n.')
    return value


Channel = Annotated[str, Depends(channel)]


def sees_private(channel: str) -> bool:
    """FR41: only the laptop (`web`, i.e. `/docs`) sees `laptop_only` documents over HTTP; for
    `discord` and `n8n` they do not exist (Eo, 12.R1 Q7)."""
    return channel == "web"


def _saved(saved) -> dict:
    return asdict(saved) | {"message": describe(saved)}


def create_app(
    api_key: str | None = None,
    *,
    warm_up: Callable[[], None] = llm.warm_up,
    model: Model | ModuleType = llm,
    embedder: Embedder | None = None,
) -> FastAPI:
    """Build the app. `api_key` defaults to AGILA_API_KEY; the other arguments are for tests."""
    key = api_key if api_key is not None else os.environ.get(KEY_VARIABLE, "")
    if not key.strip():
        raise RuntimeError(f"Missing environment variable {KEY_VARIABLE}")
    expected = key.encode()
    header = APIKeyHeader(name=KEY_HEADER, auto_error=False)

    def require_key(given: Annotated[str | None, Security(header)]) -> None:
        """APIKeyHeader only reads the header (V72); the comparison is ours, on bytes."""
        if given is None or not secrets.compare_digest(given.encode(), expected):
            raise HTTPException(401, WRONG_KEY, headers={"WWW-Authenticate": "APIKey"})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Load the model in the background so the first ask does not pay for it (V76).
        threading.Thread(target=warm_up, name="warm-up", daemon=True).start()
        yield

    app = FastAPI(title="Agila", lifespan=lifespan)
    api = APIRouter(dependencies=[Depends(require_key)])
    app.state.require_key = require_key  # for the test that no dependency is async

    @app.exception_handler(SaveError)
    @app.exception_handler(LibraryError)
    def refused(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(NotFound)
    def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(psycopg.OperationalError)
    def database_down(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": db.DATABASE_DOWN}, status_code=503)

    @app.get("/health")
    def health() -> JSONResponse:
        """No key. 200 when the database and Ollama both answer, else 503 with the sentence."""
        problems = {"database": db.check_database(), "ollama": llm.check_ollama()}
        body = {name: problem or "ok" for name, problem in problems.items()}
        return JSONResponse(body, status_code=503 if any(problems.values()) else 200)

    @api.post("/ask")
    def ask(body: AskIn, conn: Conn, channel: Channel) -> dict:
        """The checked, cited answer (FR11), or a refusal, or passages with a note. `query_log`
        has no `n8n` channel, and no workflow asks, so `n8n` is refused (DEVIATIONS 61)."""
        if channel not in CHANNELS:
            raise HTTPException(
                400, f"The {channel} channel cannot ask questions; use web or discord."
            )
        try:
            result = ask_question(conn, body.question, channel, model=model, embedder=embedder)
        except ValueError as exc:  # a blank question
            raise HTTPException(400, str(exc)) from None
        return asdict(result) | {"formatted": format_answer(result)}

    @api.get("/search")
    def find(
        conn: Conn, channel: Channel, question: str, min_similarity: float = MIN_SIMILARITY
    ) -> dict:
        """Up to 3 passages, no model call (FR10); writes nothing (FR35). `formatted` is the same
        text the CLI's `search` prints."""
        try:
            result = search(
                conn,
                question,
                min_similarity=min_similarity,
                embedder=embedder,
                include_private=sees_private(channel),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return asdict(result) | {"formatted": format_search(result)}

    @api.get("/documents")
    def documents(
        conn: Conn, channel: Channel, status: Literal["active", "archived", "all"] = "all"
    ) -> list[dict]:
        """FR18, newest first. `saved_date` is the laptop's date, so the bot formats no dates.
        Private documents are left out for `discord` and `n8n` (FR41)."""
        found = list_documents(conn, status, include_private=sees_private(channel))
        return [asdict(d) | {"saved_date": local_date(d.saved_at)} for d in found]

    @api.post("/documents/{document_id}/archive")
    def archive_document(document_id: int, conn: Conn, channel: Channel) -> dict:
        """FR19 for the bot's `/archive`; unarchive stays CLI-only (U85). A private document is
        404 for `discord` and `n8n` (FR41)."""
        change = archive(conn, document_id, include_private=sees_private(channel))
        return asdict(change) | {"message": f'Archived document {document_id} "{change.title}".'}

    @api.post("/save/text")
    def save_pasted_text(body: TextIn, conn: Conn, channel: Channel) -> dict:
        """A save from `discord` or `n8n` that meets a private document is refused (FR41, Q5)."""
        saved = save_text(
            conn,
            body.title,
            body.label,
            body.text,
            embedder,
            body.replace,
            guard_private=not sees_private(channel),
        )
        return _saved(saved)

    @api.post("/save/url")
    def save_link(body: UrlIn, conn: Conn, channel: Channel) -> dict:
        saved = save_url(
            conn,
            body.url,
            body.title,
            embedder=embedder,
            replace=body.replace,
            guard_private=not sees_private(channel),
        )
        return _saved(saved)

    @api.delete("/documents/{document_id}")
    def delete(document_id: int, conn: Conn, channel: Channel, confirm: bool = False) -> dict:
        """FR20 with the CLI's `--yes` rule (Eo): without `confirm=true` nothing is deleted and
        the reply says what would go. An unknown id is 404, and so is a private document for
        `discord` and `n8n` (FR41)."""
        visible = sees_private(channel)
        if not confirm:
            info = document_info(conn, document_id, include_private=visible)
            return asdict(info) | {
                "deleted": False,
                "message": f'Would delete document {info.document_id} "{info.title}"'
                f" ({info.source_type}, {info.chunk_count} chunks). Nothing deleted."
                " Send it again with confirm=true to delete it.",
            }
        info = delete_document(conn, document_id, include_private=visible)
        return asdict(info) | {
            "deleted": True,
            "message": f'Deleted document {info.document_id} "{info.title}" and its'
            f" {info.chunk_count} chunks.",
        }

    @api.get("/stale")
    def stale_documents(
        conn: Conn,
        channel: Channel,
        limit: Annotated[int, Query(ge=1, le=100)] = STALE_LIMIT,
        include_private: bool = False,
    ) -> dict:
        """FR39: active documents never asked about and older than 30 days, or older than 12
        months, oldest first. Private documents only with `include_private=true`, and only from
        the laptop (`web`); from `discord` or `n8n` that is 400 (FR41, Eo's Q8)."""
        if include_private and not sees_private(channel):
            raise HTTPException(400, LAPTOP_ONLY)
        result = find_stale(conn, limit=limit, include_private=include_private)
        return {
            "documents": [asdict(d) for d in result.documents],
            "total": result.total,
            "formatted": format_stale(result),
        }

    app.include_router(api)
    return app


def main(run: Callable[..., None] | None = None) -> int:
    try:
        app = create_app()
    except RuntimeError as exc:
        print(f"{exc}. Add it to .env and run: uv run --env-file .env python -m agila.api")
        return 1
    if run is None:
        import uvicorn

        run = uvicorn.run
    # No access log: `GET /search?question=...` would put the whole question in it (NFR8,
    # DEVIATIONS 55). The container runs this same `main`.
    run(app, host=os.environ.get(HOST_VARIABLE) or HOST, port=PORT, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
