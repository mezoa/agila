"""Turn retrieved passages into a checked, cited answer, or a refusal (FR11, FR12, FR13, FR34).

No HTTP and no SQL here: the model is reached through `llm` (or a fake with the same `chat`), and
the passages come from `retrieval.search`. Block j's CLI and API call `search`, then `answer`, and
only format the returned `Answer`. Nothing here writes `last_asked_at` or `query_log`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from types import ModuleType
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from agila import llm
from agila.retrieval import Passage
from agila.sentences import split_sentences

REFUSAL = "I couldn't find this in your saved material."
UNCHECKED = "The model's answer could not be checked, so here are the closest passages."
SHOWN_CHARACTERS = 300  # of each passage in the passages-only view


class Model(Protocol):
    def chat(self, messages: list[dict]) -> llm.Reply: ...


class _Citation(BaseModel):
    chunk_id: int
    sentence: int


class ModelReply(BaseModel):
    """FR12: the JSON the model must send (`llm.ANSWER_SCHEMA` asks for the same shape)."""

    answerable: bool
    answer: str
    citations: list[_Citation]


@dataclass(frozen=True)
class Cited:
    chunk_id: int
    sentence: int
    quote: str  # copied from the stored chunk text, never written by the model
    title: str
    source: str
    section: str | None  # the chunk's heading when non-empty, else None (never "")
    page: int | None
    saved_at: datetime


@dataclass(frozen=True)
class Answer:
    """`answer`: `text` + `citations`. `refusal`: `text` is the refusal sentence. `passages`
    (FR34 fallback) and `busy` (NFR15): `note` says why, and `passages` are shown instead."""

    kind: Literal["answer", "refusal", "passages", "busy"]
    text: str
    note: str | None
    citations: tuple[Cited, ...]
    passages: tuple[Passage, ...]
    model_calls: int


def section(heading: str | None) -> str | None:
    """The 7.D rule: a section name only for a non-empty heading."""
    return (heading or "").strip() or None


def _check(content: str, passages: Sequence[Passage]) -> tuple[ModelReply | None, str | None]:
    """Return (reply, None) when valid, else (None, what is wrong) in a short phrase."""
    try:
        reply = ModelReply.model_validate_json(content, strict=True)
    except ValidationError:
        return None, "the reply was not JSON with answerable, answer and citations"
    if not reply.answerable:
        return reply, None
    if not reply.answer.strip():
        return None, "the answer was empty"
    if not reply.citations:
        return None, "there were no citations"
    sizes = {p.chunk_id: len(split_sentences(p.text)) for p in passages}
    for c in reply.citations:
        if c.chunk_id not in sizes:
            return None, f"chunk_id {c.chunk_id} is not one of the passages"
        if not 1 <= c.sentence <= sizes[c.chunk_id]:
            return None, f"passage {c.chunk_id} has no sentence {c.sentence}"
    return reply, None


def _correction(problem: str, passages: Sequence[Passage]) -> dict:
    ids = ", ".join(str(p.chunk_id) for p in passages)
    return {
        "role": "user",
        "content": f"Your reply was not valid: {problem}. Reply again with JSON only. Use only"
        f" chunk_id {ids}, and only sentence numbers that exist in that passage.",
    }


def _cited(reply: ModelReply, passages: Sequence[Passage]) -> tuple[Cited, ...]:
    by_id = {p.chunk_id: p for p in passages}
    seen: list[tuple[int, int]] = []
    for c in reply.citations:  # each citation once, in the model's order
        if (c.chunk_id, c.sentence) not in seen:
            seen.append((c.chunk_id, c.sentence))
    cited = []
    for chunk_id, number in seen:
        p = by_id[chunk_id]
        quote = split_sentences(p.text)[number - 1]
        cited.append(
            Cited(
                chunk_id, number, quote, p.title, p.source, section(p.heading), p.page, p.saved_at
            )
        )
    return tuple(cited)


def _ask(question: str, passages: tuple[Passage, ...], model: Model | ModuleType) -> Answer:
    messages = llm.build_messages(question, passages)
    calls = 0
    for attempt in (1, 2):
        calls += 1
        try:
            reply = model.chat(messages)
        except llm.ModelError as exc:  # a timeout or a dead Ollama is never retried
            return Answer("passages", "", str(exc), (), passages, calls)
        parsed, problem = _check(reply.content, passages)
        if parsed is not None:
            if not parsed.answerable:
                return Answer("refusal", REFUSAL, None, (), passages, calls)
            return Answer(
                "answer", parsed.answer.strip(), None, _cited(parsed, passages), passages, calls
            )
        if attempt == 1:  # same request at temperature 0 = same reply (V63), so say what was wrong
            messages = messages + [
                {"role": "assistant", "content": reply.content},
                _correction(problem or "", passages),
            ]
    return Answer("passages", "", UNCHECKED, (), passages, calls)


def answer(
    question: str, passages: Sequence[Passage], *, model: Model | ModuleType = llm
) -> Answer:
    """FR13: no passages means a refusal and no model call. Otherwise ask the model (one call at
    a time, NFR15), check the reply (FR12), retry once, else fall back to passages (FR34)."""
    found = tuple(passages)
    if not found:
        return Answer("refusal", REFUSAL, None, (), (), 0)
    try:
        with llm.one_call_at_a_time():  # held across the retry, so no call slips in between
            return _ask(question, found, model)
    except llm.ModelBusy as exc:
        return Answer("busy", "", str(exc), (), found, 0)


def _date(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d")  # the laptop's local date


def _where(title: str, heading: str | None) -> str:
    name = section(heading)
    return f"{title} - {name}" if name else title


def format_answer(result: Answer) -> str:
    """Plain text for a terminal (FR11): answer, then each quote with its source and date."""
    if result.kind == "refusal":
        return result.text
    if result.kind == "answer":
        lines = [result.text, "", "Sources:"]
        for n, c in enumerate(result.citations, 1):
            page = f", page {c.page}" if c.page is not None else ""
            lines.append(f'{n}. "{c.quote}"')
            lines.append(
                f"   {_where(c.title, c.section)} ({c.source}{page}, saved {_date(c.saved_at)})"
            )
        return "\n".join(lines)
    lines = [result.note or "", "", "Closest passages:"]
    for n, p in enumerate(result.passages, 1):
        page = f", page {p.page}" if p.page is not None else ""
        lines.append(
            f"{n}. {_where(p.title, p.heading)} ({p.source}{page}, saved {_date(p.saved_at)})"
        )
        text = " ".join(p.text.split())
        more = "..." if len(text) > SHOWN_CHARACTERS else ""
        lines.append("   " + text[:SHOWN_CHARACTERS] + more)
    return "\n".join(lines)
