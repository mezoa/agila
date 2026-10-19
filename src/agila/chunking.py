"""Split a document into chunks that fit the embedding model's token limit (FR5)."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "fastembed"
TARGET_TOKENS = 300
CAP_TOKENS = 400

TokenCounter = Callable[[str], int]

FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.DOTALL)
HEADING = re.compile(r"^#{1,6}[ \t]+(.*\S)[ \t]*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    position: int
    heading: str
    text: str


@lru_cache(maxsize=1)
def default_counter() -> TokenCounter:
    """Load the embedding model once (cache in <repo>/.cache/fastembed) and return its counter."""
    from fastembed import TextEmbedding

    model = TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))
    return model.token_count


def embedded_text(title: str, heading: str, text: str) -> str:
    """The exact string that is embedded and counted: title, heading, chunk text (FR6)."""
    return "\n".join(part for part in (title, heading, text) if part)


def chunk_document(
    title: str,
    text: str,
    is_markdown: bool,
    count_tokens: TokenCounter | None = None,
    target: int = TARGET_TOKENS,
    cap: int = CAP_TOKENS,
) -> list[Chunk]:
    """Split by headings (Markdown), then paragraphs, aiming for `target` tokens, never over `cap`.

    Tokens are counted on the embedded string (title + heading + chunk text). The counter
    stops at 512, so only small pieces are measured: a count above `cap` always means "too big".
    """
    count = count_tokens or default_counter()
    text = text.replace("\r\n", "\n")
    if is_markdown:
        text = FRONT_MATTER.sub("", text, count=1)
        sections = _sections(text)
    else:
        sections = [("", text)]

    chunks: list[Chunk] = []
    for heading, body in sections:
        if not body.strip():
            continue
        if count(embedded_text(title, heading, "x")) >= cap:
            raise ValueError(f"Title and heading leave no room for text under {cap} tokens")

        def size(piece: str, heading: str = heading) -> int:
            return count(embedded_text(title, heading, piece))

        for piece in _split(body.strip(), size, target, cap, 0):
            chunks.append(Chunk(position=len(chunks), heading=heading, text=piece))
    return chunks


def _sections(text: str) -> list[tuple[str, str]]:
    """Cut at Markdown headings (ignoring '#' lines inside code fences)."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line)
        if match:
            sections.append((match.group(1), []))
        else:
            sections[-1][1].append(line)
    return [(heading, "\n".join(lines)) for heading, lines in sections]


# Coarse to fine: paragraphs, lines, sentences, words. Characters are the last resort.
SPLITTERS: list[tuple[Callable[[str], list[str]], str]] = [
    (lambda s: re.split(r"\n\s*\n", s), "\n\n"),
    (lambda s: s.split("\n"), "\n"),
    (SENTENCE_END.split, " "),
    (str.split, " "),
]


def _split(text: str, size: Callable[[str], int], target: int, cap: int, level: int) -> list[str]:
    """Pack pieces of one level up to `target`; a piece alone over `cap` goes down a level."""
    if size(text) <= cap and level > 0:
        return [text]
    if level >= len(SPLITTERS):
        middle = len(text) // 2
        return _split(text[:middle], size, target, cap, level) + _split(
            text[middle:], size, target, cap, level
        )

    splitter, joiner = SPLITTERS[level]
    pieces = [p.strip() for p in splitter(text) if p.strip()]
    out: list[str] = []
    current = ""
    for piece in pieces:
        if size(piece) > cap:
            if current:
                out.append(current)
                current = ""
            out.extend(_split(piece, size, target, cap, level + 1))
            continue
        candidate = f"{current}{joiner}{piece}" if current else piece
        if current and size(candidate) > target:
            out.append(current)
            current = piece
        else:
            current = candidate
    if current:
        out.append(current)
    return out
