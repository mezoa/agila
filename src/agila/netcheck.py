"""Decide whether a host may be fetched: every address it resolves to must be public (FR2).

One rule, no switch: `is_blocked_address` is the V41 rule from the research file. `vet_host`
resolves with the system resolver and refuses if the answer is empty, if the lookup fails, or if
ANY returned address is blocked. Odd spellings such as `2130706433` or `0x7f.0.0.1` are covered
because we judge what the resolver returns, never the text of the host (V42).

Known gap (accepted, see decisions.md "Download safety"): the HTTP client resolves the name again
when it connects, so a name that changes its answer in between (DNS rebinding) is not caught.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

Resolver = Callable[[str, int], Awaitable[list[str]]]

# Networks that `ipaddress` flags do not cover (V41): NAT64, IPv4-compatible, shared address space.
EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(net)
    for net in ("::/96", "64:ff9b::/96", "64:ff9b:1::/48", "100.64.0.0/10")
)


class AddressRefused(Exception):
    """The host is private, local, reserved or cannot be looked up; one readable sentence."""


def is_blocked_address(address: str) -> bool:
    """True unless `address` (text) is a normal public address; unparsable text is blocked."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 scope id
    except ValueError:
        return True
    if ip.version == 6:
        if ip.ipv4_mapped:
            return is_blocked_address(str(ip.ipv4_mapped))
        if ip.sixtofour:
            return is_blocked_address(str(ip.sixtofour))
        if ip.teredo or ip.is_site_local:
            return True
    if any(ip in net for net in EXTRA_BLOCKED):
        return True
    return (
        not ip.is_global
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
    )


async def system_resolver(host: str, port: int) -> list[str]:
    """All addresses the system resolver gives for `host`. Never uses AI_NUMERICHOST (V42)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def vet_host(host: str, port: int, resolver: Resolver | None = None) -> list[str]:
    """Resolve `host` and return its addresses, or raise AddressRefused.

    Refuses on any resolver error, an empty answer, or if ANY address is blocked (the connection
    library may try the others). `resolver` is a parameter so tests can pass a fake.
    """
    try:
        addresses = list(await (resolver or system_resolver)(host, port))
    except Exception:  # any resolver failure means refuse (CancelledError is not an Exception)
        addresses = []
    if not addresses:
        raise AddressRefused(f"The address {host} could not be looked up.")
    if any(is_blocked_address(address) for address in addresses):
        raise AddressRefused(
            f"The address {host} is private, local or reserved, so it is not fetched."
        )
    return addresses
