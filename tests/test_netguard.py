"""Self-tests of the network guard in conftest.py (block f, part 2, step 1).

The target address 192.0.2.1 is reserved for documentation (RFC 5737) and is never routed. More
important, every test below first swaps the real connect and lookup functions for recorders, so
even a broken guard would send nothing: the test then fails because a recorder was called.
"""

import asyncio
import socket
import sys
from pathlib import Path

import httpx
import pytest

pytest_plugins = ["pytester"]

DOC_ADDRESS = ("192.0.2.1", 80)
CONFTEST = Path(__file__).with_name("conftest.py")


class Recorders:
    """Swap the guard's `originals` for functions that only write down that they were called."""

    def __init__(self, guard):
        self.guard = guard
        self.calls = []
        self.saved = dict(guard.originals)

    def __enter__(self):
        for name in self.guard.originals:
            self.guard.originals[name] = lambda *args, _name=name, **kwargs: self.calls.append(
                (_name, args)
            )
        return self

    def __exit__(self, *exc):
        self.guard.originals.update(self.saved)


def test_connect_and_connect_ex_to_a_non_loopback_address_are_blocked(net_guard):
    with Recorders(net_guard) as recorded:
        for method in ("connect", "connect_ex"):
            sock = socket.socket()
            try:
                with pytest.raises(net_guard.error):
                    getattr(sock, method)(DOC_ADDRESS)
            finally:
                sock.close()
    assert recorded.calls == []  # the real function was never reached
    assert len(net_guard.take()) == 2  # both attempts were recorded (and are now acknowledged)


def test_name_lookups_of_real_hosts_are_blocked(net_guard):
    with Recorders(net_guard) as recorded:
        for call in (
            lambda: socket.getaddrinfo("example.com", 80),
            lambda: socket.getaddrinfo("192.0.2.1", 80),
            lambda: socket.getaddrinfo("2001:db8::1", 80),
            lambda: socket.gethostbyname("example.com"),
            lambda: socket.gethostbyname_ex("example.com"),
            lambda: socket.create_connection(DOC_ADDRESS, timeout=1),
        ):
            with pytest.raises(net_guard.error):
                call()
    assert recorded.calls == []
    assert len(net_guard.take()) == 6


def test_a_connect_through_the_asyncio_loop_is_blocked(net_guard):
    """The default Windows loop does not call socket.connect (U29), so it has its own patch."""

    async def attempt():
        loop = asyncio.get_running_loop()  # the loop exists before the recorders go in
        sock = socket.socket()
        sock.setblocking(False)
        try:
            with Recorders(net_guard) as recorded:
                with pytest.raises(net_guard.error):
                    await loop.sock_connect(sock, DOC_ADDRESS)
            return recorded.calls
        finally:
            sock.close()

    assert asyncio.run(attempt()) == []
    assert len(net_guard.take()) == 1


def test_httpx_cannot_reach_a_non_loopback_address(net_guard):
    async def attempt():
        async with httpx.AsyncClient() as client:
            with Recorders(net_guard) as recorded:
                with pytest.raises(httpx.ConnectError):
                    await client.get("http://192.0.2.1/")
                with pytest.raises(httpx.ConnectError):
                    await client.get("http://example.test/")
        return recorded.calls

    assert asyncio.run(attempt()) == []
    assert len(net_guard.take()) >= 2


def test_loopback_still_works_for_sockets_and_asyncio(net_guard):
    async def serve_and_ask():
        async def reply(reader, writer):
            writer.write(b"pong")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(reply, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        data = await reader.read(4)
        writer.close()
        server.close()
        return data

    assert asyncio.run(serve_and_ask()) == b"pong"
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        with socket.create_connection(("localhost", port), timeout=2):
            pass
    assert net_guard.attempts == []


SWALLOWED = """
import socket

def test_swallows_the_error(net_guard):
    net_guard.originals["connect"] = lambda sock, address: None  # even a broken guard sends nothing
    try:
        socket.socket().connect(("192.0.2.1", 80))
    except OSError:
        pass  # the code under test hides the error

def test_acknowledged_attempt_passes(net_guard):
    net_guard.originals["connect"] = lambda sock, address: None
    try:
        socket.socket().connect(("192.0.2.1", 80))
    except OSError:
        pass
    assert len(net_guard.take()) == 1
"""


def test_an_error_swallowed_by_the_code_still_fails_the_test(pytester):
    pytester.makeconftest(CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(test_inner=SWALLOWED)
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-q")
    result.assert_outcomes(passed=2, errors=1)  # the first test errors at teardown
    result.stdout.fnmatch_lines(["*Blocked network attempts*connect to*192.0.2.1*"])


@pytest.mark.skipif(sys.platform != "win32", reason="the Proactor patch exists on Windows only")
def test_the_windows_loop_patch_is_installed(net_guard):
    assert "proactor_connect" in net_guard.originals
