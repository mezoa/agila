import ipaddress
import socket
import sys

import pytest

from agila import db

TEST_DB = "agila_test"


# --- network guard: no test may leave this computer (block f, part 2, step 1) ---


class NetworkBlockedError(OSError):
    """A test (or a library it calls) tried to leave the loopback interface."""


def _is_loopback_name(host) -> bool:
    """True for `localhost` and numeric loopback addresses; nothing else is a safe name."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback


class NetGuard:
    """Wraps the Python-level name lookups and connects for one test.

    Allowed: connecting to 127.0.0.0/8, ::1 and Unix sockets; looking up None, `localhost` and
    numeric loopback addresses. Anything else raises NetworkBlockedError and is also recorded in
    `attempts`, so a library that swallows the error still fails the test at teardown unless the
    test itself reads the record with `take()`. `originals` holds the real functions the wrappers
    call; the self-tests swap them for recorders so that even a broken guard sends nothing.
    Limit: native code (libpq for Postgres, onnxruntime) does not go through these functions.
    """

    error = NetworkBlockedError

    def __init__(self):
        self.attempts: list[str] = []
        self.originals = {
            "getaddrinfo": socket.getaddrinfo,
            "gethostbyname": socket.gethostbyname,
            "gethostbyname_ex": socket.gethostbyname_ex,
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
        }
        if sys.platform == "win32":
            # asyncio's default Windows loop connects here, not through socket.connect (U29)
            from asyncio import windows_events

            self.originals["proactor_connect"] = windows_events.IocpProactor.connect

    def take(self) -> list[str]:
        """Return the recorded attempts and clear them (acknowledges them)."""
        taken, self.attempts = self.attempts, []
        return taken

    def _block(self, what: str, target) -> None:
        self.attempts.append(f"{what} {target}")
        raise NetworkBlockedError(
            f"Tests may only use the loopback interface; blocked {what} {target}"
        )

    def _check_lookup(self, host) -> None:
        if host is not None and not _is_loopback_name(host):
            self._block("lookup of", host)

    def _check_connect(self, family, address) -> None:
        if family == getattr(socket, "AF_UNIX", None):
            return
        host = address[0] if isinstance(address, tuple) and address else address
        if not _is_loopback_name(host):
            self._block("connect to", address)

    def install(self, monkeypatch) -> None:
        guard = self

        def getaddrinfo(host, *args, **kwargs):
            guard._check_lookup(host)
            return guard.originals["getaddrinfo"](host, *args, **kwargs)

        def gethostbyname(host):
            guard._check_lookup(host)
            return guard.originals["gethostbyname"](host)

        def gethostbyname_ex(host):
            guard._check_lookup(host)
            return guard.originals["gethostbyname_ex"](host)

        def connect(sock, address):
            guard._check_connect(sock.family, address)
            return guard.originals["connect"](sock, address)

        def connect_ex(sock, address):
            guard._check_connect(sock.family, address)
            return guard.originals["connect_ex"](sock, address)

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        monkeypatch.setattr(socket, "gethostbyname", gethostbyname)
        monkeypatch.setattr(socket, "gethostbyname_ex", gethostbyname_ex)
        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
        if "proactor_connect" in self.originals:
            from asyncio import windows_events

            def proactor_connect(proactor, conn, address):
                guard._check_connect(conn.family, address)
                return guard.originals["proactor_connect"](proactor, conn, address)

            monkeypatch.setattr(windows_events.IocpProactor, "connect", proactor_connect)


@pytest.fixture(autouse=True)
def net_guard(monkeypatch):
    """Every test runs with the guard on; there is no switch to turn it off."""
    guard = NetGuard()
    guard.install(monkeypatch)
    yield guard
    if guard.attempts:
        pytest.fail(
            "Blocked network attempts (not allowed in tests): " + "; ".join(guard.attempts),
            pytrace=False,
        )


def _recreate_test_database():
    assert TEST_DB == "agila_test"  # never drop anything else
    with db.connect(dbname="postgres", register=False) as admin:
        admin.autocommit = True
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")


@pytest.fixture
def empty_db():
    """Name of a fresh, empty database; dropped afterwards. Never touches `agila`."""
    _recreate_test_database()
    yield TEST_DB
    with db.connect(dbname="postgres", register=False) as admin:
        admin.autocommit = True
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture
def conn(empty_db):
    with db.connect(dbname=empty_db, register=False) as plain:
        db.migrate(plain)
    with db.connect(dbname=empty_db) as migrated:
        yield migrated
