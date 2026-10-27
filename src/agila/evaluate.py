"""The golden-set evaluation (block l, FR33): a frozen library in `agila_eval`, hit@3, refusals.

It opens only the database `agila_eval`, by that name, and calls `retrieval.search` (and, for full
answers, `ask.answer`), never the ask flow of `questions.py`, so an evaluation run changes neither
`last_asked_at` nor `query_log` (FR35). It reads `eval/questions.txt` and `eval/hit-phrases.txt`;
it never reads `eval/answer-key.md`.

A hit (M1, Eo 9.L1): the question's phrase, lowercased with all whitespace removed, appears in
the text of one of the raw top 3 passages (no threshold). A question with no phrase is
unanswerable.
"""

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType

import psycopg

from agila import db, embed, export, llm, retrieval
from agila.ask import Answer, Model, answer
from agila.chunking import MODEL_NAME, TokenCounter, chunk_document
from agila.embed import Embedder, default_embedder
from agila.library import SaveError, save_markdown, save_text, save_url
from agila.retrieval import Passage, SearchResult
from agila.urls import UrlError, normalize_url
from agila.web import WebError, extract_page, fetch_html

EVAL_DB = "agila_eval"  # the only database an evaluation opens; never `agila`
MAINTENANCE_DB = "postgres"  # used only to create and drop EVAL_DB
HALVES = ("dev", "held-out")
QUESTION_COUNT = 20
ANSWERABLE_PER_HALF = 7  # and 3 unanswerable per half (U49)
WEB_MANIFEST = "web-pages.json"  # url, file, sha256, date of each frozen page


class EvalError(Exception):
    """One readable sentence for anything that stops an evaluation."""


@dataclass(frozen=True)
class Question:
    number: int
    half: str
    text: str


def _rows(path: Path, columns: int) -> list[tuple[int, list[str]]]:
    """(line number, stripped parts) for each line that is not blank or a `#` comment."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        raise EvalError(f"File not found: {path}") from None
    except (OSError, UnicodeDecodeError):
        raise EvalError(f"Could not read {path} as UTF-8 text.") from None
    rows = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", columns - 1)]
        if len(parts) != columns or not parts[0].isdigit() or not all(parts):
            raise EvalError(f"{Path(path).name} line {line_number} is not in the expected format.")
        rows.append((line_number, parts))
    return rows


def read_questions(path: Path) -> list[Question]:
    """`NN | half | question` lines: exactly 20, each number once, half `dev` or `held-out`."""
    name = Path(path).name
    questions: list[Question] = []
    for line_number, (number, half, text) in _rows(path, 3):
        if half not in HALVES:
            raise EvalError(f"{name} line {line_number}: the half must be dev or held-out.")
        if any(q.number == int(number) for q in questions):
            raise EvalError(f"{name} line {line_number}: question {number} is repeated.")
        questions.append(Question(int(number), half, text))
    if len(questions) != QUESTION_COUNT:
        raise EvalError(f"{name} has {len(questions)} questions, not {QUESTION_COUNT}.")
    return questions


def read_hit_phrases(path: Path, questions: Sequence[Question]) -> dict[int, str]:
    """`NN | phrase` lines, one per answerable question: 7 per half. Errors never show a phrase."""
    halves = {q.number: q.half for q in questions}
    phrases: dict[int, str] = {}
    for line_number, (number, phrase) in _rows(path, 2):
        if int(number) not in halves:
            raise EvalError(f"{Path(path).name} line {line_number}: no question {number}.")
        if int(number) in phrases:
            raise EvalError(f"{Path(path).name} line {line_number}: question {number} is repeated.")
        phrases[int(number)] = phrase
    for half in HALVES:
        count = sum(1 for number in phrases if halves[number] == half)
        if count != ANSWERABLE_PER_HALF:
            raise EvalError(
                f"{Path(path).name} has {count} phrases for the {half} half,"
                f" not {ANSWERABLE_PER_HALF}."
            )
    return phrases


def normalize(text: str) -> str:
    """Lowercase, all whitespace removed (Eo, 9.L1)."""
    return "".join(text.lower().split())


def is_hit(phrase: str, passages: Sequence[Passage]) -> bool:
    """True when the phrase is in the text of one of the first 3 passages."""
    wanted = normalize(phrase)
    return any(wanted in normalize(p.text) for p in passages[:3])


@dataclass(frozen=True)
class Outcome:
    """One question's raw top 3 (no threshold): numbers only, never passage text."""

    question: Question
    answerable: bool
    hit: bool  # always False for an unanswerable question
    similarities: tuple[float, ...]  # best first

    @property
    def best(self) -> float | None:
        return self.similarities[0] if self.similarities else None


@dataclass(frozen=True)
class Score:
    threshold: float
    answerable: int
    hits: int  # M1: raw top 3, no threshold
    hits_by_half: dict[str, int]
    unanswerable: int
    refused: int  # M2: unanswerable questions below the threshold, so no model call
    refused_by_half: dict[str, int]
    false_refusals: int  # answerable questions the threshold would refuse (Eo, 9.L1)


def _below(outcome: Outcome, threshold: float) -> bool:
    """Refused by the threshold: `search` keeps only passages at or above it (V94)."""
    return outcome.best is None or outcome.best < threshold


def score(outcomes: Sequence[Outcome], threshold: float) -> Score:
    answerable = [o for o in outcomes if o.answerable]
    unanswerable = [o for o in outcomes if not o.answerable]
    refused = [o for o in unanswerable if _below(o, threshold)]
    return Score(
        threshold,
        len(answerable),
        sum(o.hit for o in answerable),
        {h: sum(o.hit for o in answerable if o.question.half == h) for h in HALVES},
        len(unanswerable),
        len(refused),
        {h: sum(o.question.half == h for o in refused) for h in HALVES},
        sum(_below(o, threshold) for o in answerable),
    )


def gap(outcomes: Sequence[Outcome]) -> float | None:
    """Lowest best score of an answerable question minus the highest of an unanswerable one."""
    yes = [o.best for o in outcomes if o.answerable and o.best is not None]
    no = [o.best for o in outcomes if not o.answerable and o.best is not None]
    return min(yes) - max(no) if yes and no else None


def _errors(outcomes: Sequence[Outcome], threshold: float) -> int:
    """Answerable questions refused plus unanswerable questions let through."""
    return sum(_below(o, threshold) == o.answerable for o in outcomes)


def propose_threshold(outcomes: Sequence[Outcome]) -> tuple[float, int]:
    """(threshold, errors) on the given questions, from 0.00 to 1.00 in steps of 0.01.

    The values with the fewest errors form runs; take the HIGHEST run (ties lean toward refusing,
    FR13) and its middle, rounded up. With no overlap the zero-error run is the gap between the
    best unanswerable and the worst answerable score, so this is the midpoint of the gap.
    """
    errors = [_errors(outcomes, step / 100) for step in range(101)]
    fewest = min(errors)
    high = max(step for step in range(101) if errors[step] == fewest)
    low = high
    while low > 0 and errors[low - 1] == fewest:
        low -= 1
    return (low + high + 1) // 2 / 100, fewest


Connect = Callable[..., psycopg.Connection]


def _guard(name: str) -> None:
    """Refuse every database name except the literal EVAL_DB, and EVAL_DB itself if it is the
    real library's name (`POSTGRES_DB`, never printed)."""
    real = os.environ.get("POSTGRES_DB", "")
    if name != EVAL_DB or name.lower() == real.lower():
        raise EvalError(f"The evaluation only uses the database {EVAL_DB}; refused {name!r}.")


def open_eval(connect: Connect = db.connect) -> psycopg.Connection:
    """A connection to EVAL_DB, by name. Nothing else in this module opens a library."""
    _guard(EVAL_DB)
    return connect(dbname=EVAL_DB)


def _admin(connect: Connect, sql: str) -> None:
    with connect(dbname=MAINTENANCE_DB, register=False) as admin:
        admin.autocommit = True  # CREATE and DROP DATABASE cannot run inside a transaction
        admin.execute(sql)


def create_eval_db(connect: Connect = db.connect, name: str = EVAL_DB) -> list[str]:
    """Drop and create EVAL_DB, then apply the same migrations as the real library.

    `name` exists only so a test can see the guard refuse; its only accepted value is EVAL_DB.
    """
    _guard(name)
    _admin(connect, f"DROP DATABASE IF EXISTS {EVAL_DB} WITH (FORCE)")
    _admin(connect, f"CREATE DATABASE {EVAL_DB}")
    with connect(dbname=EVAL_DB, register=False) as plain:
        return db.migrate(plain)


def drop_eval_db(connect: Connect = db.connect, name: str = EVAL_DB) -> None:
    _guard(name)
    _admin(connect, f"DROP DATABASE IF EXISTS {EVAL_DB} WITH (FORCE)")


def read_urls(path: Path) -> list[str]:
    """The links in `web-sources.txt`, in order (blank and `#` lines skipped)."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        raise EvalError(f"File not found: {path}") from None
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def web_file(number: int) -> str:
    return f"web-{number:02d}.html"


def web_chunks(url: str, html: str, count_tokens: TokenCounter | None = None) -> list[str]:
    """The chunk texts `library.save_url` would store for this HTML (same title rule, same
    line-ending rule, same chunker), so two copies of a page can be compared without a database."""
    page_title, text = extract_page(html)
    title = page_title or normalize_url(url)
    text = text.replace("\r\n", "\n")
    return [c.text for c in chunk_document(title, text, False, count_tokens)]


def freeze(
    urls: Sequence[str],
    folder: Path,
    fetch: Callable[[str], str] = fetch_html,
    count_tokens: TokenCounter | None = None,
    today: date | None = None,
) -> list[str]:
    """Download each page ONCE and store its HTML in `folder` (Eo, 9.L1; U51).

    All or nothing: every page is fetched and checked before anything is written. Each file is
    written as UTF-8 with no line-ending change and read back; the read-back copy must give the
    same chunks as the downloaded one. Refuses to overwrite: a new exam version is a manual act.
    """
    folder = Path(folder)
    names = [web_file(n) for n in range(1, len(urls) + 1)]
    if (folder / WEB_MANIFEST).exists() or any((folder / name).exists() for name in names):
        raise EvalError(f"The web pages are already frozen in {folder}; nothing was changed.")
    pages = []
    for number, url in enumerate(urls, 1):
        try:
            html = fetch(url)
            chunks = web_chunks(url, html, count_tokens)
        except (WebError, UrlError) as exc:
            raise EvalError(
                f"Web page {number} could not be frozen: {exc} Nothing was written."
            ) from exc
        pages.append((url, html, chunks))
    written = []
    try:
        manifest = []
        for name, (url, html, chunks) in zip(names, pages, strict=True):
            path = folder / name
            with open(path, "w", encoding="utf-8", newline="") as out:
                out.write(html)
            written.append(path)
            raw = path.read_bytes()
            if web_chunks(url, raw.decode("utf-8"), count_tokens) != chunks:
                raise EvalError(f"The stored copy of {name} gives other chunks; nothing was kept.")
            manifest.append(
                {
                    "url": url,
                    "file": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "fetched": (today or date.today()).isoformat(),
                }
            )
        (folder / WEB_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return names


STORED_CHUNKS = (
    "SELECT c.text FROM chunks c JOIN documents d ON d.id = c.document_id"
    " WHERE d.source_url = %s AND d.status = 'active' ORDER BY c.position"
)


def _frozen_pages(folder: Path, urls: Sequence[str]) -> list[tuple[str, str]]:
    """(url, html) of each frozen page, checked against the manifest before anything is saved."""
    try:
        entries = json.loads((folder / WEB_MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EvalError("The web pages are not frozen yet: run evaluate freeze first.") from None
    if [entry["url"] for entry in entries] != list(urls):
        raise EvalError(f"{WEB_MANIFEST} does not list the links of web-sources.txt in order.")
    pages = []
    for entry in entries:
        try:
            raw = (folder / entry["file"]).read_bytes()
        except FileNotFoundError:
            raise EvalError(f"The frozen page {entry['file']} is missing.") from None
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise EvalError(f"{entry['file']} has changed since it was frozen; nothing was saved.")
        pages.append((entry["url"], raw.decode("utf-8")))
    return pages


def build(
    conn: psycopg.Connection, folder: Path, urls: Sequence[str], embedder: Embedder | None = None
) -> tuple[int, int]:
    """Save the frozen library with the app's own save code: `.md` files as Markdown, `.txt` files
    as text (title = file name without extension, label = file name), each web page through
    `save_url` with its stored HTML (no network). Then check that every web page's stored chunks
    are the chunks of its frozen HTML (U51). Returns (documents, chunks). The Obsidian export is
    off: these are not Eo's documents, and their ids would collide with the real library's."""
    folder = Path(folder)
    pages = _frozen_pages(folder, urls)
    try:
        with export.off():
            for path in sorted(folder.glob("*.md")):
                save_markdown(conn, path, embedder=embedder)
            for path in sorted(folder.glob("*.txt")):
                text = path.read_text(encoding="utf-8-sig")
                save_text(conn, path.stem, path.name, text, embedder=embedder)
            for url, html in pages:
                save_url(conn, url, fetcher=lambda _url, html=html: html, embedder=embedder)
    except SaveError as exc:
        raise EvalError(f"The build stopped: {exc}") from exc
    except UnicodeDecodeError:
        raise EvalError("A library file is not UTF-8 text; the build stopped.") from None
    with conn.transaction():
        for number, (url, html) in enumerate(pages, 1):
            stored = [row[0] for row in conn.execute(STORED_CHUNKS, (url,))]
            if stored != web_chunks(url, html):
                raise EvalError(f"Web page {number} was stored with other chunks than its HTML.")
        return conn.execute(
            "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)"
        ).fetchone()


@dataclass(frozen=True)
class RetrievalRun:
    outcomes: list[Outcome]
    seconds: list[float]  # one per search, in order; the first includes loading the embedder

    @property
    def cold(self) -> float | None:
        return self.seconds[0] if self.seconds else None

    @property
    def warm(self) -> list[float]:
        """M3: the 10 searches after the cold one (fewer when fewer questions ran)."""
        return self.seconds[1:11]


def run_retrieval(
    conn: psycopg.Connection,
    questions: Sequence[Question],
    phrases: dict[int, str],
    *,
    embedder: Embedder | None = None,
    with_instruction: bool | None = None,
    search: Callable[..., SearchResult] | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> RetrievalRun:
    """The raw top 3 of each question (M1: no threshold), timed (M3). Read-only (FR35).

    `with_instruction`: None = the app's query-prefix setting; True or False forces it."""
    search = search or retrieval.search
    conn.read_only = True  # every transaction from here on refuses writes (U50)
    outcomes, seconds = [], []
    for question in questions:
        started = clock()
        result = search(
            conn,
            question.text,
            min_similarity=-1.0,
            embedder=embedder,
            with_instruction=with_instruction,
        )
        seconds.append(clock() - started)
        phrase = phrases.get(question.number)
        hit = phrase is not None and is_hit(phrase, result.passages)
        sims = tuple(p.similarity for p in result.passages)
        outcomes.append(Outcome(question, phrase is not None, hit, sims))
    return RetrievalRun(outcomes, seconds)


def run_answers(
    conn: psycopg.Connection,
    questions: Sequence[Question],
    threshold: float,
    *,
    embedder: Embedder | None = None,
    model: Model | ModuleType = llm,
    clock: Callable[[], float] = time.perf_counter,
) -> list[tuple[Question, Answer, float]]:
    """Search with the threshold, then `ask.answer`, each question once and timed (M4).

    Not the ask flow of the CLI or the API: nothing is logged and `last_asked_at` is never set
    (FR35). Read-only, like `run_retrieval`.
    """
    conn.read_only = True
    results = []
    for question in questions:
        started = clock()
        found = retrieval.search(conn, question.text, min_similarity=threshold, embedder=embedder)
        result = answer(question.text, found.passages, model=model)
        results.append((question, result, clock() - started))
    return results


# --- the command: python -m agila.cli evaluate <action> (Eo, 9.L2) ---

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


@dataclass(frozen=True)
class Files:
    folder: Path

    @property
    def questions(self) -> Path:
        return self.folder / "questions.txt"

    @property
    def phrases(self) -> Path:
        return self.folder / "hit-phrases.txt"

    @property
    def web_sources(self) -> Path:
        return self.folder / "web-sources.txt"

    @property
    def library(self) -> Path:
        return self.folder / "library"


def _dev_run(
    connect: Connect, files: Files, embedder: Embedder, with_instruction: bool
) -> list[Outcome]:
    """The raw top 3 of the dev half only, on a fresh read-only connection (U50)."""
    questions = read_questions(files.questions)
    phrases = read_hit_phrases(files.phrases, questions)
    dev = [q for q in questions if q.half == "dev"]
    with open_eval(connect) as conn:
        return run_retrieval(
            conn, dev, phrases, embedder=embedder, with_instruction=with_instruction
        ).outcomes


def _hit(outcome: Outcome) -> str:
    return ("yes" if outcome.hit else "no") if outcome.answerable else "-"


def _best(outcome: Outcome) -> str:
    return "none" if outcome.best is None else f"{outcome.best:.3f}"


def _summary(label: str, outcomes: list[Outcome]) -> str:
    s = score(outcomes, retrieval.MIN_SIMILARITY)
    g = gap(outcomes)
    threshold, errors = propose_threshold(outcomes)
    return (
        f"{label}: dev hits {s.hits} of {s.answerable}, gap"
        f" {'n/a' if g is None else f'{g:+.3f}'}, proposed threshold {threshold:.2f}"
        f" (dev errors {errors})."
    )


def _prefix(connect: Connect, files: Files, embedder: Embedder) -> list[str]:
    plain = _dev_run(connect, files, embedder, with_instruction=False)
    prefixed = _dev_run(connect, files, embedder, with_instruction=True)
    lines = ["Dev half only. Q  answerable | without prefix | with prefix"]
    for a, b in zip(plain, prefixed, strict=True):
        lines.append(
            f"{a.question.number:02d}  {'yes' if a.answerable else 'no '}"
            f" | hit {_hit(a):<3} best {_best(a)} | hit {_hit(b):<3} best {_best(b)}"
        )
    lines.append(_summary("Without prefix", plain))
    lines.append(_summary("With prefix", prefixed))
    return lines


def _threshold(
    connect: Connect, files: Files, embedder: Embedder, prefix: bool | None
) -> list[str]:
    prefix = embed.USE_QUERY_INSTRUCTION if prefix is None else prefix  # None: the app's setting
    outcomes = _dev_run(connect, files, embedder, with_instruction=prefix)
    lines = [f"Dev half only, {'with' if prefix else 'without'} the query prefix, best first:"]
    for o in sorted(outcomes, key=lambda o: o.best if o.best is not None else -2.0, reverse=True):
        kind = "answerable" if o.answerable else "unanswerable"
        lines.append(f"{_best(o)}  {kind:<12}  Q{o.question.number:02d}")
    g = gap(outcomes)
    threshold, errors = propose_threshold(outcomes)
    lines.append(f"Gap: {'n/a (one side is empty)' if g is None else f'{g:+.3f}'}.")
    lines.append(f"Proposed threshold: {threshold:.2f} (dev errors: {errors}).")
    return lines


BASELINE = "baseline.json"
# FR33: the run fails when either count drops below the baseline (plan Q7); the rest is reported.
GATED = (("hits", "hit@3"), ("refused", "Refusals of unanswerable questions"))


def _git_commit() -> str | None:
    """The commit the run used, with `+changes` when the working tree differs from it."""
    root = EVAL_DIR.parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return commit + ("+changes" if changes else "")


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _numbers(s: Score, run: RetrievalRun, today: date) -> dict:
    """What the baseline holds: counts, settings and times. No question, phrase or passage text."""
    warm = _median(run.warm)
    return {
        "date": today.isoformat(),
        "git_commit": _git_commit(),
        "embedding_model": MODEL_NAME,
        "query_prefix": embed.USE_QUERY_INSTRUCTION,
        "threshold": s.threshold,
        "answerable": s.answerable,
        "hits": s.hits,
        "hits_dev": s.hits_by_half["dev"],
        "hits_held_out": s.hits_by_half["held-out"],
        "false_refusals": s.false_refusals,
        "unanswerable": s.unanswerable,
        "refused": s.refused,
        "refused_dev": s.refused_by_half["dev"],
        "refused_held_out": s.refused_by_half["held-out"],
        "m3_cold_seconds": None if run.cold is None else round(run.cold, 3),
        "m3_median_seconds": None if warm is None else round(warm, 3),
        "m3_warm_searches": len(run.warm),
    }


def _seconds(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:.{digits}f} s"


def _retrieval(
    connect: Connect,
    files: Files,
    embedder: Embedder | None,
    baseline: Path | None,
    save: bool,
    clock: Callable[[], float],
    today: date,
) -> tuple[list[str], int]:
    """Step 11: all 20 questions once (M1, M2, M3), then the FR33 baseline check or save."""
    path = Path(baseline) if baseline else files.folder / BASELINE
    if save and path.exists():
        raise EvalError(f"{path} already exists; nothing was run. Move it away to save a new one.")
    if not save and not path.exists():
        raise EvalError(
            f"No baseline at {path}; nothing was run. The first full run is:"
            " evaluate retrieval --save-baseline"
        )
    questions = read_questions(files.questions)
    phrases = read_hit_phrases(files.phrases, questions)
    with open_eval(connect) as conn:  # a fresh connection; run_retrieval makes it read-only
        run = run_retrieval(conn, questions, phrases, embedder=embedder, clock=clock)
    s = score(run.outcomes, retrieval.MIN_SIMILARITY)
    numbers = _numbers(s, run, today)
    per_half = {h: sum(o.answerable and o.question.half == h for o in run.outcomes) for h in HALVES}
    no_half = {
        h: sum(not o.answerable and o.question.half == h for o in run.outcomes) for h in HALVES
    }
    lines = [
        f"All {len(questions)} questions, raw top 3, query prefix"
        f" {'on' if numbers['query_prefix'] else 'off'}, threshold {s.threshold:.2f}.",
        f"M1 hit@3: {s.hits} of {s.answerable} ({s.hits / max(s.answerable, 1):.2f});"
        f" dev {s.hits_by_half['dev']} of {per_half['dev']},"
        f" held-out {s.hits_by_half['held-out']} of {per_half['held-out']}.",
        f"False refusals (answerable below {s.threshold:.2f}): {s.false_refusals}"
        f" of {s.answerable}.",
        f"M2 refused with no model call: {s.refused} of {s.unanswerable};"
        f" dev {s.refused_by_half['dev']} of {no_half['dev']},"
        f" held-out {s.refused_by_half['held-out']} of {no_half['held-out']}.",
        f"M3 time to passages: cold {_seconds(run.cold, 2)}, median"
        f" {_seconds(_median(run.warm), 3)} over {len(run.warm)} warm searches.",
    ]
    if save:
        path.write_text(json.dumps(numbers, indent=2) + "\n", encoding="utf-8")
        return lines + [f"Saved {path}."], 0
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        drops = [
            f"{label} dropped: {numbers[key]}, baseline {saved[key]}."
            for key, label in GATED
            if numbers[key] < saved[key]
        ]
    except (ValueError, KeyError, TypeError):
        raise EvalError(f"{path} is not a readable baseline; nothing was compared.") from None
    if drops:
        return lines + drops, 1
    return lines + [
        f"Not below the baseline {path.name}: hits {numbers['hits']} (baseline {saved['hits']}),"
        f" refusals {numbers['refused']} (baseline {saved['refused']})."
    ], 0


def _cell(text: str) -> str:
    """One Markdown table cell: whitespace collapsed, `|` escaped."""
    return " ".join(str(text).split()).replace("|", "\\|")


EXCERPT = 100  # about this many characters of the answer in the grading sheet
EXCERPT_MAX = 160  # never more (before the "…")
SENTENCE_END = re.compile(r"[.!?](?= |$)")


def excerpt(text: str) -> str:
    """About 100 characters of an answer, in whole words (Eo, 2026-10-26).

    Whitespace is collapsed. Up to 100 characters: all of it. Otherwise the word being written at
    character 100 is finished (a word is a run of non-space characters, so `₱40,000–₱60,000/month`
    stays whole); if a sentence ends between there and 160 characters, the excerpt stops at that
    sentence end; if not, it stops at the end of the word with "…". A word that would pass 160
    is dropped: the cut goes to the last space before 100 (a single word longer than that, with
    no space before 100, is the only case cut inside a word).
    """
    text = " ".join(text.split())
    if len(text) <= EXCERPT:
        return text
    if text[EXCERPT - 1] == " ":  # the 100th character is a space: no word is being written
        end = EXCERPT - 1
    else:
        end = text.find(" ", EXCERPT)
        end = len(text) if end == -1 else end
    for match in SENTENCE_END.finditer(text):
        if end <= match.end() <= EXCERPT_MAX:
            return text[: match.end()]
        if match.end() > EXCERPT_MAX:
            break
    if end > EXCERPT_MAX:
        space = text.rfind(" ", 0, EXCERPT)
        end = space if space > 0 else EXCERPT
    return text[:end] + ("…" if end < len(text) else "")


def grading_sheet(results: Sequence[tuple[Question, Answer, float]], today: date) -> str:
    """M10 and U15: one row per citation for Eo to grade once; answers that were not given are
    listed as `no answer`. It holds quotes from the library, so it goes in git-ignored eval/runs/.
    """
    lines = [
        f"# Grading sheet, {today.isoformat()} (M10, U15)",
        "",
        "Fill in once. Supports the answer: **yes** = the quote alone states what the answer says;"
        " **partly** = related but missing a key part; **no** = it does not say it.",
        "",
        "| Q | Half | Answer (about 100 characters, whole words) | Cited chunk:sentence"
        " | Cited quote | Right document? (y/n) | Supports the answer? (yes / partly / no)"
        " | Note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for question, result, _ in results:
        q = f"{question.number:02d}"
        if result.kind != "answer":
            lines.append(f"| {q} | {question.half} | no answer ({result.kind}) | - | - | - | - | |")
            continue
        short = _cell(excerpt(result.text))  # cut first, then escape `|` (never half of `\|`)
        for cited in result.citations:
            lines.append(
                f"| {q} | {question.half} | {short} | {cited.chunk_id}:{cited.sentence}"
                f" | {_cell(cited.quote)} | | | |"
            )
    return "\n".join(lines) + "\n"


def m4_rows(results: Sequence[tuple[Question, Answer, float]]) -> tuple[float | None, list[float]]:
    """(cold seconds, warm seconds) for M4. Only answers that called the model count: a threshold
    refusal takes no model time and would pull the median down (bug of 2026-10-26, DEVIATIONS 44).
    The first of them is the cold one (the model loads on its first call), reported alone; M4 is
    over the next 10 (plan Q8)."""
    timed = [s for _, a, s in results if a.model_calls >= 1]
    return (timed[0] if timed else None), timed[1:11]


def _answers(
    connect: Connect,
    files: Files,
    embedder: Embedder | None,
    model: Model | ModuleType,
    clock: Callable[[], float],
    today: date,
    version: Callable[[], str | None],
) -> list[str]:
    """Step 12: the 14 answerable questions once each (M4), and the grading sheet (M10)."""
    sheet = files.folder / "runs" / f"grading-{today.isoformat()}.md"
    if sheet.exists():
        raise EvalError(f"{sheet} already exists; nothing was run. Move it away first.")
    questions = read_questions(files.questions)
    phrases = read_hit_phrases(files.phrases, questions)
    answerable = [q for q in questions if q.number in phrases]
    with open_eval(connect) as conn:  # a fresh connection; run_answers makes it read-only
        results = run_answers(
            conn,
            answerable,
            retrieval.MIN_SIMILARITY,
            embedder=embedder,
            model=model,
            clock=clock,
        )
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.write_text(grading_sheet(results, today), encoding="utf-8")
    cold, warm = m4_rows(results)
    lines = [
        f"Q{q.number:02d}  {q.half:<8}  {a.kind:<8}  citations {len(a.citations)}"
        f"  model calls {a.model_calls}  {s:.1f} s"
        for q, a, s in results
    ]
    left_out = sum(a.model_calls == 0 for _, a, _ in results)
    lines.append(
        f"Cold first answer {_seconds(cold, 1)}."
        f" M4: median {_seconds(_median(warm), 1)},"
        f" slowest {_seconds(max(warm) if warm else None, 1)} over {len(warm)} warm answers"
        f" that called the model ({len(warm)} of {len(results)} questions; the cold one and"
        f" {left_out} with no model call left out). Ollama {version() or 'version unknown'}."
    )
    lines.append(f"Grading sheet: {sheet}")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agila.cli evaluate")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("freeze", help="download the 3 web pages ONCE into eval/library (network)")
    sub.add_parser("build", help="create agila_eval and save the frozen library into it")
    sub.add_parser("prefix", help="dev half: raw top 3 with and without the query prefix")
    threshold = sub.add_parser("threshold", help="dev half: best scores and a proposed threshold")
    setting = threshold.add_mutually_exclusive_group()
    setting.add_argument(
        "--prefix", dest="prefix", action="store_const", const=True, help="force the prefix on"
    )
    setting.add_argument(
        "--no-prefix", dest="prefix", action="store_const", const=False, help="force it off"
    )
    run = sub.add_parser(
        "retrieval", help="ALL 20 questions (held-out included): M1, M2, M3 and the baseline"
    )
    run.add_argument(
        "--save-baseline", action="store_true", help="first run: write eval/baseline.json"
    )
    run.add_argument(
        "--baseline", type=Path, help="compare with this file (default: eval/baseline.json)"
    )
    sub.add_parser(
        "answers", help="the 14 answerable questions with the model: M4 and the grading sheet"
    )
    sub.add_parser("drop", help="delete the database agila_eval (the frozen files stay)")
    return parser


def main(
    argv: list[str],
    connect: Connect = db.connect,
    folder: Path = EVAL_DIR,
    fetch: Callable[[str], str] = fetch_html,
    embedder: Embedder | None = None,
    model: Model | ModuleType = llm,
    clock: Callable[[], float] = time.perf_counter,
    today: date | None = None,
    version: Callable[[], str | None] = llm.ollama_version,
) -> int:
    """One evaluation action. It never opens the real library: only `agila_eval` (and `postgres`
    to create or drop it)."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed the usage or the help
        return int(exc.code or 0)
    files = Files(Path(folder))
    today = today or date.today()
    code = 0
    try:
        if args.action == "freeze":
            urls = read_urls(files.web_sources)
            names = freeze(urls, files.library, fetch)
            lines = [
                f"Froze {len(names)} pages into {files.library} ({', '.join(names)});"
                " the stored copies give the same chunks."
            ]
        elif args.action == "build":
            urls = read_urls(files.web_sources)
            create_eval_db(connect)
            with open_eval(connect) as conn:
                documents, chunks = build(conn, files.library, urls, embedder)
            lines = [
                f"Built {EVAL_DB}: {documents} documents, {chunks} chunks. Web pages: stored"
                f" chunks match the frozen HTML ({len(urls)} of {len(urls)})."
            ]
        elif args.action == "drop":
            drop_eval_db(connect)
            lines = [f"Dropped {EVAL_DB}."]
        elif args.action == "prefix":
            lines = _prefix(connect, files, embedder or default_embedder())
        elif args.action == "threshold":
            lines = _threshold(connect, files, embedder or default_embedder(), args.prefix)
        elif args.action == "retrieval":
            lines, code = _retrieval(
                connect, files, embedder, args.baseline, args.save_baseline, clock, today
            )
        else:
            lines = _answers(connect, files, embedder, model, clock, today, version)
    except EvalError as exc:
        print(exc)
        return 1
    except RuntimeError as exc:  # a missing POSTGRES_* variable (db.connect never prints values)
        print(f"{exc}. Run with: uv run --env-file .env python -m agila.cli evaluate ...")
        return 1
    except psycopg.OperationalError:
        print(
            f"Cannot open the database {EVAL_DB}. Start the database (docker compose up -d db);"
            " if it runs, build the library first: evaluate build"
        )
        return 1
    print("\n".join(lines))
    return code
