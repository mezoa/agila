"""The web API (FR26): save, ask, search, list and delete behind a key; `/health` and `/docs` open.

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
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from agila import db, llm
from agila.ask import Model, format_answer
from agila.embed import Embedder
from agila.library import (
    LibraryError,
    NotFound,
    SaveError,
    delete_document,
    describe,
    document_info,
    list_documents,
    save_text,
    save_url,
)
from agila.questions import ask_question
from agila.retrieval import PROVISIONAL_MIN_SIMILARITY, search

HOST = "127.0.0.1"  # FR26; inside Docker (block k) the publish must stay 127.0.0.1:8000:8000
PORT = 8000
KEY_HEADER = "X-API-Key"
KEY_VARIABLE = "AGILA_API_KEY"
WRONG_KEY = "Missing or wrong API key."
CHANNEL = "web"  # [assumed] until the bot (block m) needs "discord"


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
    def ask(body: AskIn, conn: Conn) -> dict:
        """The checked, cited answer (FR11), or a refusal, or passages with a note."""
        try:
            result = ask_question(conn, body.question, CHANNEL, model=model, embedder=embedder)
        except ValueError as exc:  # a blank question
            raise HTTPException(400, str(exc)) from None
        return asdict(result) | {"formatted": format_answer(result)}

    @api.get("/search")
    def find(conn: Conn, question: str, min_similarity: float = PROVISIONAL_MIN_SIMILARITY) -> dict:
        """Up to 3 passages, no model call (FR10); writes nothing (FR35)."""
        try:
            return asdict(search(conn, question, min_similarity=min_similarity, embedder=embedder))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @api.get("/documents")
    def documents(conn: Conn) -> list[dict]:
        return [asdict(d) for d in list_documents(conn)]

    @api.post("/save/text")
    def save_pasted_text(body: TextIn, conn: Conn) -> dict:
        saved = save_text(conn, body.title, body.label, body.text, embedder, body.replace)
        return _saved(saved)

    @api.post("/save/url")
    def save_link(body: UrlIn, conn: Conn) -> dict:
        return _saved(save_url(conn, body.url, body.title, embedder=embedder, replace=body.replace))

    @api.delete("/documents/{document_id}")
    def delete(document_id: int, conn: Conn, confirm: bool = False) -> dict:
        """FR20 with the CLI's `--yes` rule (Eo): without `confirm=true` nothing is deleted and
        the reply says what would go. An unknown id is 404."""
        if not confirm:
            info = document_info(conn, document_id)
            return asdict(info) | {
                "deleted": False,
                "message": f'Would delete document {info.document_id} "{info.title}"'
                f" ({info.source_type}, {info.chunk_count} chunks). Nothing deleted."
                " Send it again with confirm=true to delete it.",
            }
        info = delete_document(conn, document_id)
        return asdict(info) | {
            "deleted": True,
            "message": f'Deleted document {info.document_id} "{info.title}" and its'
            f" {info.chunk_count} chunks.",
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
    run(app, host=HOST, port=PORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
