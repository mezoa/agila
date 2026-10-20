"""Download a page with a total time limit and pull out its readable text (FR2).

Only the first part of FR2 is here (block f, part 1). Private-address blocking, redirects, the
5 MB cap and the content-type check are Day 5, so nothing calls these from a command line yet.
"""

import asyncio
import re

import httpx
import trafilatura

TIMEOUT_SECONDS = 15.0
MIN_CHARACTERS = 200
MIN_SENTENCES = 3
MIN_WORDS_PER_SENTENCE = 3


class WebError(Exception):
    """A page that cannot be saved; the message is one readable sentence."""


class FetchError(WebError):
    """The download failed."""


class PageRejected(WebError):
    """The page was downloaded but has too little readable text."""


async def fetch_html_async(
    url: str, timeout: float = TIMEOUT_SECONDS, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Download `url` and return its text. `timeout` is a TOTAL wall-clock limit in seconds.

    httpx's own per-step timeouts are switched off (`timeout=None`) because they would restart at
    every step; `asyncio.timeout` cancels the whole download when the total is used up.
    Redirects are not followed yet (Day 5). `transport` lets tests pass httpx.MockTransport.
    """
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                transport=transport, follow_redirects=False, timeout=None
            ) as client:
                response = await client.get(url)
                body = response.text
    except TimeoutError:
        raise FetchError(f"The page took longer than {timeout:g} seconds to download.") from None
    except httpx.ConnectError:
        raise FetchError("Could not connect to the page. Check the link and network.") from None
    except httpx.HTTPError:
        raise FetchError("The page could not be downloaded.") from None
    if 300 <= response.status_code < 400:
        raise FetchError("The page redirects; redirects are not supported yet.")
    if response.status_code != 200:
        raise FetchError(f"The page answered with status {response.status_code}.")
    return body


def fetch_html(
    url: str, timeout: float = TIMEOUT_SECONDS, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """Sync wrapper around `fetch_html_async` (uses asyncio.run, Python 3.12 here).

    It must NOT be called from inside a running event loop (asyncio.run cannot nest); doing so
    raises FetchError. Call `fetch_html_async` with `await` from async code instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch_html_async(url, timeout, transport))
    raise FetchError("fetch_html cannot run inside an event loop; await fetch_html_async instead.")


# Words before a full stop that do not end a sentence. "etc." is left out: it often does.
ABBREVIATIONS = {"e.g.", "i.e.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.", "fig.", "approx."}
DOTTED_INITIALS = re.compile(r"^(?:[a-z]\.){2,}$")  # u.s. , a.m.
BREAK = re.compile(r"(?P<end>[.!?]+)\s+|\n+")


def count_sentences(text: str) -> int:
    """Count sentences [assumed rule, FR2].

    Cut at ".", "!" or "?" followed by whitespace, and at line breaks, but not after an
    abbreviation such as "e.g."; "3.5" has no space after the dot, so it never splits. A piece
    of fewer than 3 words is joined to the piece before it (or after it, at the start), so a menu
    line like "Home" never counts. The count is the number of pieces left.
    """
    pieces: list[str] = []
    start = 0
    for match in BREAK.finditer(text):
        end = match.group("end")
        if end is not None:
            last_word = text[start : match.end("end")].split()[-1].lower()
            if end == "." and (last_word in ABBREVIATIONS or DOTTED_INITIALS.match(last_word)):
                continue
            pieces.append(text[start : match.end("end")])
        else:
            pieces.append(text[start : match.start()])
        start = match.end()
    pieces.append(text[start:])

    units: list[str] = []
    carry = ""
    for piece in (p.strip() for p in pieces if p.strip()):
        piece = f"{carry} {piece}".strip()
        carry = ""
        if len(piece.split()) >= MIN_WORDS_PER_SENTENCE:
            units.append(piece)
        elif units:
            units[-1] += f" {piece}"
        else:
            carry = piece
    return len(units)


def check_text(text: str | None) -> str:
    """Return the text if it passes the FR2 rules, else raise PageRejected (one sentence)."""
    if not text or not text.strip():
        raise PageRejected("No readable text found on the page.")
    if len(" ".join(text.split())) < MIN_CHARACTERS:
        raise PageRejected(f"The page has under {MIN_CHARACTERS} characters of text.")
    if count_sentences(text) < MIN_SENTENCES:
        raise PageRejected(f"The page has fewer than {MIN_SENTENCES} sentences of text.")
    return text


def extract_page(html: str) -> tuple[str | None, str]:
    """Return (page title or None, main text) from HTML; raise PageRejected if the text is thin."""
    text = check_text(trafilatura.extract(html))
    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title or "").strip() if metadata else ""
    return (title or None), text
