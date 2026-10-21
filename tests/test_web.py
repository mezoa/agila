import asyncio
import ipaddress
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from agila.web import (
    MAX_BYTES,
    FetchError,
    PageRejected,
    _make_client,
    _read_page,
    check_text,
    count_sentences,
    extract_page,
    fetch_html,
    fetch_html_async,
)

FIXTURES = Path(__file__).parent / "fixtures"
URL = "http://example.test/page"
PUBLIC = (
    "8.8.8.8"  # plain data in the fake resolver: nothing connects to it (guard + MockTransport)
)
HTML = "text/html; charset=utf-8"


def resolver(names=None):
    """A fake name lookup. IP literals answer as themselves, listed names as listed.

    Any other name is an ordinary public host (PUBLIC).
    """
    names = {} if names is None else names

    async def lookup(host, port):
        if host in names:
            return names[host]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [PUBLIC]
        return [host]

    return lookup


def page(body=b"<p>hello</p>", status=200, content_type=HTML, **headers):
    """A response built on a stream.

    Responses made with `text=` or `content=` are already read, and reading them again with
    aiter_raw raises StreamConsumed (real responses never are).
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    all_headers = dict(headers)
    if content_type is not None:
        all_headers["content-type"] = content_type
    return httpx.Response(status, headers=all_headers, stream=httpx.ByteStream(body))


def redirect(location, status=302):
    return httpx.Response(status, headers={"location": location})


def site(routes):
    """(transport, calls): `routes` maps a full URL to a function that makes the response."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return routes[str(request.url)]()

    return httpx.MockTransport(handler), calls


def fetch(url, transport, **kwargs):
    kwargs.setdefault("resolver", resolver())
    return fetch_html(url, transport=transport, **kwargs)


class LazyBody(httpx.AsyncByteStream):
    """A body of `total` bytes made on demand, counting how much was handed out."""

    def __init__(self, total, step=65536, then=None):
        self.total, self.step, self.then, self.produced = total, step, then, 0

    async def __aiter__(self):
        while self.produced < self.total:
            size = min(self.step, self.total - self.produced)
            self.produced += size
            yield b"a" * size
        if self.then is not None:
            raise self.then


# --- the download, through httpx.MockTransport (no network, no server) ---


def test_200_returns_the_body_text():
    transport, calls = site({URL: lambda: page("<p>hello</p>")})
    assert fetch(URL, transport) == "<p>hello</p>"
    assert calls == [URL]


@pytest.mark.parametrize("status", [403, 404, 500])
def test_other_statuses_name_the_status(status):
    transport, _ = site({URL: lambda: page("no", status=status)})
    with pytest.raises(FetchError, match=f"status {status}"):
        fetch(URL, transport)


def test_a_redirect_status_without_a_location_is_just_a_status():
    transport, _ = site({URL: lambda: httpx.Response(302)})
    with pytest.raises(FetchError, match="status 302"):
        fetch(URL, transport)


def test_connection_error_is_one_readable_sentence():
    def refuse(request):
        raise httpx.ConnectError("boom with details", request=request)

    with pytest.raises(FetchError) as err:
        fetch(URL, httpx.MockTransport(refuse))
    assert str(err.value).startswith("Could not connect")
    assert "boom" not in str(err.value)  # no raw library text


def test_any_other_http_error_is_readable_too():
    def broken(request):
        raise httpx.ReadError("connection reset", request=request)

    with pytest.raises(FetchError, match="could not be downloaded"):
        fetch(URL, httpx.MockTransport(broken))


def test_total_time_limit_cancels_a_stalled_answer():
    async def stall(request):
        await asyncio.sleep(5)
        return page("too late")

    started = time.perf_counter()
    with pytest.raises(FetchError, match=r"longer than 0\.2 seconds"):
        fetch(URL, httpx.MockTransport(stall), timeout=0.2)
    assert time.perf_counter() - started < 1.5  # about 0.2 s, not 5 s


def test_the_total_time_limit_also_covers_the_name_lookup():
    async def slow_lookup(host, port):
        await asyncio.sleep(5)
        return [PUBLIC]

    transport, calls = site({URL: lambda: page()})
    started = time.perf_counter()
    with pytest.raises(FetchError, match=r"longer than 0\.2 seconds"):
        fetch_html(URL, timeout=0.2, transport=transport, resolver=slow_lookup)
    assert time.perf_counter() - started < 1.5
    assert calls == []


def test_fetch_html_refuses_to_run_inside_an_event_loop():
    transport, _ = site({URL: lambda: page("x")})

    async def caller():
        return fetch(URL, transport)

    with pytest.raises(FetchError, match="event loop"):
        asyncio.run(caller())


def test_async_version_works_inside_an_event_loop():
    transport, _ = site({URL: lambda: page("async body")})
    body = asyncio.run(fetch_html_async(URL, transport=transport, resolver=resolver()))
    assert body == "async body"


# --- the address check, on every hop (FR2) ---


@pytest.fixture
def local_server():
    """A real server on 127.0.0.1 that counts the requests it gets: (port, list of paths)."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = b"<p>reached</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], hits
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "LOCALHOST"])
def test_localhost_is_refused_before_anything_is_sent(local_server, host):
    port, hits = local_server
    # No fake: the real name lookup runs (the test guard allows loopback lookups only)
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch_html(f"http://{host}:{port}/")
    assert hits == []  # the server never saw a request


@pytest.mark.parametrize(
    "host", ["10.0.0.5", "192.168.1.20", "172.16.0.9", "169.254.169.254", "100.64.0.1", "0.0.0.0"]
)
def test_private_ip_addresses_are_refused_with_no_request(host):
    transport, calls = site({})
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch(f"http://{host}/latest", transport)
    assert calls == []


@pytest.mark.parametrize("host", ["[::1]", "[::ffff:127.0.0.1]", "[fe80::1]", "[fd00::1]"])
def test_private_ipv6_literals_are_refused(host):
    transport, calls = site({})
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch(f"http://{host}/", transport)
    assert calls == []


@pytest.mark.parametrize("host", ["2130706433", "0x7f.0.0.1", "127.1"])
def test_odd_ip_spellings_are_refused_by_what_the_lookup_returns(host):
    # httpx keeps these spellings as written; a system that reads them as 127.0.0.1 is refused
    transport, calls = site({})
    lookup = resolver({host: ["127.0.0.1"]})
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch(f"http://{host}/", transport, resolver=lookup)
    assert calls == []


def test_a_name_that_resolves_to_a_private_address_is_refused():
    transport, calls = site({})
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch("http://evil.test/", transport, resolver=resolver({"evil.test": ["10.0.0.5"]}))
    assert calls == []


def test_a_name_with_public_and_private_addresses_is_refused():
    transport, calls = site({})
    lookup = resolver({"mixed.test": [PUBLIC, "192.168.0.7"]})
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch("http://mixed.test/", transport, resolver=lookup)
    assert calls == []


def test_a_name_that_cannot_be_looked_up_is_refused():
    async def broken(host, port):
        raise OSError("no such host")

    transport, calls = site({})
    with pytest.raises(FetchError, match="could not be looked up"):
        fetch(URL, transport, resolver=broken)
    assert calls == []


def test_a_link_httpx_cannot_parse_gets_one_sentence():
    transport, calls = site({})
    with pytest.raises(FetchError, match="could not be understood"):
        fetch("http://0177.0.0.1/", transport)
    assert calls == []


@pytest.mark.parametrize("url", ["ftp://example.test/f", "htp://example.test/", "example.test"])
def test_only_http_and_https_start_a_download(url):
    transport, calls = site({})
    with pytest.raises(FetchError):
        fetch(url, transport)
    assert calls == []


# --- redirects by hand, at most 5 ---


def test_relative_and_absolute_redirects_are_followed():
    transport, calls = site(
        {
            "http://one.test/a": lambda: redirect("b"),
            "http://one.test/b": lambda: redirect("/c/d"),
            "http://one.test/c/d": lambda: redirect("//two.test/e"),
            "http://two.test/e": lambda: redirect("https://two.test/f?x=1#part"),
            "https://two.test/f?x=1": lambda: page("final"),
        }
    )
    assert fetch("http://one.test/a", transport) == "final"
    assert len(calls) == 5


def test_a_redirect_to_a_private_address_is_refused_after_one_request():
    transport, calls = site({"http://one.test/": lambda: redirect("http://inside.test/admin")})
    lookup = resolver({"inside.test": ["10.0.0.5"]})
    with pytest.raises(FetchError, match="inside.test is private, local or reserved"):
        fetch("http://one.test/", transport, resolver=lookup)
    assert calls == ["http://one.test/"]


@pytest.mark.parametrize(
    "target", ["http://127.0.0.1:8000/", "http://169.254.169.254/", "http://[::1]/"]
)
def test_a_redirect_to_a_private_ip_literal_is_refused(target):
    transport, calls = site({"http://one.test/": lambda: redirect(target)})
    with pytest.raises(FetchError, match="private, local or reserved"):
        fetch("http://one.test/", transport)
    assert calls == ["http://one.test/"]


def test_a_redirect_to_another_scheme_is_refused():
    transport, calls = site({"http://one.test/": lambda: redirect("ftp://one.test/file")})
    with pytest.raises(FetchError, match="Only http and https"):
        fetch("http://one.test/", transport)
    assert calls == ["http://one.test/"]


def test_a_redirect_loop_is_refused():
    transport, calls = site(
        {"http://one.test/x": lambda: redirect("/y"), "http://one.test/y": lambda: redirect("/x")}
    )
    with pytest.raises(FetchError, match="in a circle"):
        fetch("http://one.test/x", transport)
    assert calls == ["http://one.test/x", "http://one.test/y"]


def test_loop_detection_ignores_the_fragment():
    transport, calls = site({"http://one.test/x": lambda: redirect("#again")})
    with pytest.raises(FetchError, match="in a circle"):
        fetch("http://one.test/x#start", transport)
    assert calls == ["http://one.test/x"]


def test_an_empty_location_is_a_loop_too():
    transport, _ = site({"http://one.test/": lambda: redirect("")})
    with pytest.raises(FetchError, match="in a circle"):
        fetch("http://one.test/", transport)


def _chain(length):
    routes = {f"http://one.test/{k}": (lambda k=k: redirect(f"/{k + 1}")) for k in range(length)}
    routes[f"http://one.test/{length}"] = lambda: page("end")
    return site(routes)


def test_five_redirects_are_allowed():
    transport, calls = _chain(5)
    assert fetch("http://one.test/0", transport) == "end"
    assert len(calls) == 6


def test_the_sixth_redirect_is_refused():
    transport, calls = _chain(6)
    with pytest.raises(FetchError, match="more than 5 times"):
        fetch("http://one.test/0", transport)
    assert len(calls) == 6  # the 6th answer was a redirect, and it was not followed


# --- size, content type and compression ---


def _streamed(body, **headers):
    headers.setdefault("content-type", HTML)
    return httpx.Response(200, headers=headers, stream=body)


def test_a_50_mb_body_without_a_length_stops_near_5_mb():
    body = LazyBody(50 * 1024 * 1024)
    transport, _ = site({URL: lambda: _streamed(body)})
    with pytest.raises(FetchError, match="larger than 5 MB"):
        fetch(URL, transport)
    assert MAX_BYTES < body.produced <= MAX_BYTES + 2 * body.step  # never reads the whole 50 MB


def test_an_honest_50_mb_length_is_refused_before_any_body_is_read():
    body = LazyBody(50 * 1024 * 1024)
    transport, _ = site({URL: lambda: _streamed(body, **{"content-length": str(50 * 1024 * 1024)})})
    with pytest.raises(FetchError, match="larger than 5 MB"):
        fetch(URL, transport)
    assert body.produced == 0


def test_exactly_5_mb_is_accepted():
    transport, _ = site({URL: lambda: page(b"a" * MAX_BYTES)})
    assert len(fetch(URL, transport)) == MAX_BYTES


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "application/json"])
def test_a_wrong_content_type_is_refused_before_the_body_is_read(content_type):
    body = LazyBody(1000)
    transport, _ = site({URL: lambda: _streamed(body, **{"content-type": content_type})})
    with pytest.raises(FetchError, match="not HTML or plain text"):
        fetch(URL, transport)
    assert body.produced == 0


def test_a_missing_content_type_is_refused():
    transport, _ = site({URL: lambda: page("<p>x</p>", content_type=None)})
    with pytest.raises(FetchError, match="does not say what kind of file"):
        fetch(URL, transport)


@pytest.mark.parametrize(
    "content_type",
    ["text/html", "TEXT/HTML; Charset=UTF-8", "text/plain", "application/xhtml+xml; charset=utf-8"],
)
def test_html_xhtml_and_plain_text_are_accepted(content_type):
    transport, _ = site({URL: lambda: page("ok", content_type=content_type)})
    assert fetch(URL, transport) == "ok"


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "zstd", "gzip, br"])
def test_a_compressed_answer_is_refused_and_identity_was_requested(encoding):
    seen = []

    def handler(request):
        seen.append(request.headers["accept-encoding"])
        return page(b"\x1f\x8b not really gzip", **{"content-encoding": encoding})

    with pytest.raises(FetchError, match="compressed and was not accepted"):
        fetch(URL, httpx.MockTransport(handler))
    assert seen == ["identity"]


def test_content_encoding_identity_is_fine():
    transport, _ = site({URL: lambda: page("plain", **{"content-encoding": "identity"})})
    assert fetch(URL, transport) == "plain"


def test_the_charset_in_the_header_is_used_and_an_unknown_one_does_not_crash():
    latin = site({URL: lambda: page(b"caf\xe9", content_type="text/html; charset=latin-1")})
    assert fetch(URL, latin[0]) == "café"
    odd = site({URL: lambda: page(b"caf\xc3\xa9", content_type="text/html; charset=no-such")})
    assert fetch(URL, odd[0]) == "café"


def test_a_connection_that_breaks_mid_body_gets_one_sentence():
    body = LazyBody(1000, then=httpx.RemoteProtocolError("peer closed"))
    transport, _ = site({URL: lambda: _streamed(body)})
    with pytest.raises(FetchError, match="closed before the whole page arrived"):
        fetch(URL, transport)


# --- the few tests that need a real socket: loopback only, below the address check ---


async def _serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _read_from(port, path="/"):
    async with _make_client() as client:
        async with client.stream("GET", f"http://127.0.0.1:{port}{path}") as response:
            return await _read_page(response)


def _answer(raw):
    async def handler(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(raw)
        await writer.drain()
        writer.close()

    return handler


def test_a_content_length_larger_than_the_body_gets_one_sentence():
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 100\r\n\r\n" + b"a" * 20

    async def main():
        server, port = await _serve(_answer(raw))
        try:
            return await _read_from(port)
        finally:
            server.close()

    with pytest.raises(FetchError, match="closed before the whole page arrived"):
        asyncio.run(main())


def test_a_content_length_smaller_than_the_body_cuts_the_page_silently():
    """Known limit (V45): httpx stops at the declared length, so this cannot be detected."""
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 10\r\n\r\n" + b"b" * 5000

    async def main():
        server, port = await _serve(_answer(raw))
        try:
            return await _read_from(port)
        finally:
            server.close()

    assert asyncio.run(main()) == "b" * 10


def test_a_real_gzip_answer_is_refused_by_its_header_without_decompressing():
    """U27: a server that compresses anyway is refused from the header; no body is read."""
    import gzip

    body = gzip.compress(b"a" * (40 * 1024 * 1024))  # 40 MB of text, about 40 KB on the wire
    head = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Encoding: gzip\r\n"
        b"Content-Length: %d\r\n\r\n" % len(body)
    )

    async def main():
        server, port = await _serve(_answer(head + body))
        try:
            return await _read_from(port)
        finally:
            server.close()

    with pytest.raises(FetchError, match="compressed and was not accepted"):
        asyncio.run(main())


def test_proxy_environment_variables_are_ignored(monkeypatch):
    """U26: a client that trusts the environment sends the request to the proxy; ours does not."""
    proxy_hits, target_hits = [], []
    reply = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\nhi"

    def noting(hits):
        async def handler(reader, writer):
            hits.append((await reader.readuntil(b"\r\n\r\n")).split(b"\r\n")[0])
            writer.write(reply)
            await writer.drain()
            writer.close()

        return handler

    async def main():
        proxy, proxy_port = await _serve(noting(proxy_hits))
        target, target_port = await _serve(noting(target_hits))
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy_port}")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        url = f"http://127.0.0.1:{target_port}/page"
        try:
            async with httpx.AsyncClient(trust_env=True) as trusting:
                await trusting.get(url)
            premise = (len(proxy_hits), len(target_hits))
            proxy_hits.clear()
            target_hits.clear()
            body = await _read_from(target_port, "/page")
            return premise, (len(proxy_hits), len(target_hits)), body
        finally:
            proxy.close()
            target.close()

    premise, ours, body = asyncio.run(main())
    assert premise == (1, 0)  # the environment proxy took the request: the risk is real
    assert ours == (0, 1)  # our client went straight to the target
    assert body == "hi"
    assert _make_client().trust_env is False


# --- sentence counting (assumed rule) ---


def test_three_plain_sentences_count_as_three():
    assert count_sentences("The cat sat down. The dog barked loudly! Did the bird fly away?") == 3


def test_a_decimal_number_does_not_split_a_sentence():
    # "3.5" has no space after the dot, so it is not a break
    assert count_sentences("We tested version 3.5 of the tool today. It worked well.") == 2


def test_an_abbreviation_does_not_create_a_sentence():
    # Naive splitting at every ". " would give 4 pieces here; there are 2 sentences
    text = "We tested version 3.5 of the tool, e.g. the new one. It worked well, i.e. no errors."
    assert count_sentences(text) == 2


def test_decimals_and_abbreviations_do_not_help_a_thin_page_pass():
    text = "Version 3.5 is out, e.g. for testing. Use it, i.e. try it now. Dr. Smith agrees."
    assert count_sentences(text) == 3  # three real sentences: counted once each, not more
    assert count_sentences("Prices rose 3.5 percent, e.g. in May, vs. last year.") == 1


def test_dotted_initials_do_not_split():
    assert count_sentences("The U.S. office opens at 9 a.m. every day. It closes late.") == 2


def test_menu_lines_add_at_most_one_sentence_however_long_the_menu():
    # Pieces under 3 words are joined together, so a menu of any length counts once and can
    # never reach the 3 sentences needed
    assert count_sentences("Home\nAbout us\nContact\nPrivacy policy\nSign in") == 1
    assert count_sentences("\n".join(["Menu item"] * 40)) == 1


def test_very_short_sentences_are_joined_not_counted_alone():
    assert count_sentences("Yes. No. Maybe.") == 1
    assert count_sentences("") == 0


# --- the text rules (200 characters, 3 sentences) ---


def test_none_and_empty_are_rejected():
    for value in (None, "", "   \n "):
        with pytest.raises(PageRejected, match="No readable text"):
            check_text(value)


def _three_sentences_of_length(n):
    """Three real sentences whose whitespace-collapsed length is exactly n characters."""
    start = "Alpha beta gamma delta epsilon zeta. Eta theta iota kappa lambda mu. Nu xi "
    text = start + "o" * (n - len(start) - 1) + "."
    assert len(" ".join(text.split())) == n
    assert count_sentences(text) == 3
    return text


def test_199_characters_fail_and_200_pass():
    with pytest.raises(PageRejected, match="under 200 characters"):
        check_text(_three_sentences_of_length(199))
    exact = _three_sentences_of_length(200)
    assert check_text(exact) == exact


def test_whitespace_runs_are_collapsed_before_counting_characters():
    sentence = "This is a sentence with seven words."
    padded = (sentence + " " * 100 + "\n\n") * 3  # over 400 raw characters, about 110 collapsed
    assert len(padded) > 200
    with pytest.raises(PageRejected, match="under 200 characters"):
        check_text(padded)


def test_two_sentences_fail_and_three_pass():
    sentence = (
        "This sentence is written with a good number of ordinary words, "
        "so it is long enough to count as a real sentence. "
    )
    assert len(sentence) > 100  # two of them are over 200 characters on their own
    with pytest.raises(PageRejected, match="fewer than 3 sentences"):
        check_text(sentence * 2)
    assert check_text(sentence * 3)


# --- the three saved fixtures ---


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_article_fixture_gives_its_text_without_the_menu():
    title, text = extract_page(_read("article.html"))
    assert title == "How Agila Saves a Page"
    assert "Agila is a small assistant" in text
    assert "If nothing is close enough" in text
    for menu_text in ("Blog", "Contact", "Privacy", "Copyright"):
        assert menu_text not in text


def test_menus_fixture_is_rejected():
    with pytest.raises(PageRejected, match="under 200 characters"):
        extract_page(_read("menus.html"))


def test_empty_fixture_is_rejected():
    with pytest.raises(PageRejected, match="No readable text"):
        extract_page(_read("empty.html"))


def test_login_wall_fixture_is_rejected():
    # A typical wall is a heading, one prompt and a form: far under 200 characters of text
    with pytest.raises(PageRejected, match="under 200 characters"):
        extract_page(_read("login_wall.html"))
