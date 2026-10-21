"""Download a page safely and pull out its readable text (FR2).

The download follows FR2: only http and https, a TOTAL 15-second limit, every address checked
before each request (the first one and every redirect hop), redirects followed by hand (at most 5),
HTML or plain text only, at most 5 MB. Text extraction and the 200-character and 3-sentence rules
are further down.
"""

import asyncio
import re

import httpx
import trafilatura

from agila.netcheck import AddressRefused, Resolver, vet_host
from agila.urls import UrlError, check_url

TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 5
MAX_BYTES = 5 * 1024 * 1024  # 5 MiB [assumed, FR2]
ALLOWED_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
MIN_CHARACTERS = 200
MIN_SENTENCES = 3
MIN_WORDS_PER_SENTENCE = 3


class WebError(Exception):
    """A page that cannot be saved; the message is one readable sentence."""


class FetchError(WebError):
    """The download failed."""


class PageRejected(WebError):
    """The page was downloaded but has too little readable text."""


def _make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The one client used for every download.

    httpx's own per-step timeouts are off (`timeout=None`): `asyncio.timeout` in the caller is the
    TOTAL limit. Redirects are followed by hand. `trust_env=False` ignores proxy environment
    variables (U26). `Accept-Encoding: identity` asks for an uncompressed body (U27).
    """
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        timeout=None,
        trust_env=False,
        headers={"Accept-Encoding": "identity"},
    )


def _without_fragment(url: str) -> str:
    return str(httpx.URL(url).copy_with(fragment=None))


async def _read_page(response: httpx.Response) -> str:
    """Check the status and headers first, then read the body, stopping at MAX_BYTES."""
    if response.status_code != 200:
        raise FetchError(f"The page answered with status {response.status_code}.")
    content_type = response.headers.get("content-type", "")
    if not content_type.strip():
        raise FetchError("The page does not say what kind of file it is, so it is not saved.")
    if content_type.split(";", 1)[0].strip().lower() not in ALLOWED_TYPES:
        raise FetchError("The page is not HTML or plain text.")
    if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
        raise FetchError("The page is compressed and was not accepted.")
    declared = response.headers.get("content-length", "")
    if declared.strip().isdigit() and int(declared) > MAX_BYTES:
        raise FetchError("The page is larger than 5 MB.")
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_raw():  # raw: no decompression code ever runs
            total += len(chunk)
            if total > MAX_BYTES:
                raise FetchError("The page is larger than 5 MB.")
            chunks.append(chunk)
    except httpx.RemoteProtocolError:
        raise FetchError("The connection closed before the whole page arrived.") from None
    body = b"".join(chunks)
    try:
        return body.decode(response.charset_encoding or "utf-8", errors="replace")
    except LookupError:  # a charset name Python does not know
        return body.decode("utf-8", errors="replace")


async def _fetch(client: httpx.AsyncClient, url: str, resolver: Resolver | None) -> str:
    """Hop loop: scheme and address checks on every hop, redirects by hand, at most 5."""
    current = _without_fragment(check_url(url))  # a fragment is never sent, so it never counts
    seen = {current}
    redirects = 0
    while True:
        check_url(current)  # scheme and host, again on every hop
        parsed = httpx.URL(current)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        await vet_host(parsed.host, port, resolver)
        async with client.stream("GET", current) as response:
            following = response.next_request  # None unless a usable Location came with a 3xx
            if following is None:
                return await _read_page(response)
        redirects += 1
        if redirects > MAX_REDIRECTS:
            raise FetchError(f"The page redirects more than {MAX_REDIRECTS} times.")
        current = _without_fragment(str(following.url))
        if current in seen:
            raise FetchError("The page redirects in a circle.")
        seen.add(current)


async def fetch_html_async(
    url: str,
    timeout: float = TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver | None = None,
) -> str:
    """Download `url` and return its text. `timeout` is a TOTAL wall-clock limit in seconds.

    `transport` lets tests pass httpx.MockTransport; `resolver` lets tests pass a fake name
    lookup (see netcheck.vet_host). Every failure is a FetchError with one readable sentence.
    """
    try:
        async with asyncio.timeout(timeout):
            async with _make_client(transport) as client:
                return await _fetch(client, url, resolver)
    except TimeoutError:
        raise FetchError(f"The page took longer than {timeout:g} seconds to download.") from None
    except (UrlError, AddressRefused) as exc:
        raise FetchError(str(exc)) from None
    except httpx.InvalidURL:
        raise FetchError("The link could not be understood.") from None
    except httpx.ConnectError:
        raise FetchError("Could not connect to the page. Check the link and network.") from None
    except httpx.HTTPError:
        raise FetchError("The page could not be downloaded.") from None


def fetch_html(
    url: str,
    timeout: float = TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver | None = None,
) -> str:
    """Sync wrapper around `fetch_html_async` (uses asyncio.run, Python 3.12 here).

    It must NOT be called from inside a running event loop (asyncio.run cannot nest); doing so
    raises FetchError. Call `fetch_html_async` with `await` from async code instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch_html_async(url, timeout, transport, resolver))
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
