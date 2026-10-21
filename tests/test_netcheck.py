import asyncio

import pytest

from agila.netcheck import AddressRefused, is_blocked_address, vet_host

# The V41 table (research file): every address the candidate rule was run on.
BLOCKED = [
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0",
    "224.0.0.1", "240.0.0.1", "255.255.255.255", "100.64.0.1", "192.0.2.1", "198.18.0.1",
    "::1", "::", "fe80::1", "fc00::1", "fd00::1", "ff02::1", "2001:db8::1", "64:ff9b::7f00:1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::127.0.0.1", "2002:7f00:1::", "fec0::1",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2", "fe80::1%12",
]  # fmt: skip
ALLOWED = [
    "8.8.8.8", "1.1.1.1", "93.184.216.34", "::ffff:8.8.8.8", "2002:808:808::",
    "2606:4700:4700::1111",
]  # fmt: skip


@pytest.mark.parametrize("address", BLOCKED)
def test_private_local_and_reserved_addresses_are_blocked(address):
    assert is_blocked_address(address)


@pytest.mark.parametrize("address", ALLOWED)
def test_ordinary_public_addresses_are_allowed(address):
    assert not is_blocked_address(address)


@pytest.mark.parametrize("text", ["", "localhost", "2130706433", "0x7f.0.0.1", "127.1", "nonsense"])
def test_text_that_is_not_an_address_is_blocked(text):
    assert is_blocked_address(text)


def _fake(answers):
    async def resolver(host, port):
        value = answers[host]
        if isinstance(value, Exception):
            raise value
        return value

    return resolver


def _vet(host, answers, port=80):
    return asyncio.run(vet_host(host, port, _fake(answers)))


def test_a_public_answer_is_returned_unchanged():
    assert _vet("a.test", {"a.test": ["8.8.8.8", "2606:4700:4700::1111"]}) == [
        "8.8.8.8",
        "2606:4700:4700::1111",
    ]


@pytest.mark.parametrize("answer", ["10.0.0.5", "192.168.1.20", "169.254.169.254", "127.0.0.1"])
def test_a_name_that_resolves_to_a_private_address_is_refused(answer):
    with pytest.raises(AddressRefused, match="private, local or reserved"):
        _vet("evil.test", {"evil.test": [answer]})


def test_one_blocked_address_among_public_ones_refuses_the_host():
    with pytest.raises(AddressRefused, match="private, local or reserved"):
        _vet("mixed.test", {"mixed.test": ["8.8.8.8", "10.0.0.5"]})
    with pytest.raises(AddressRefused, match="private, local or reserved"):
        _vet("mixed6.test", {"mixed6.test": ["2606:4700:4700::1111", "::1"]})


@pytest.mark.parametrize("host", ["2130706433", "0x7f.0.0.1", "127.1"])
def test_odd_spellings_are_refused_by_what_the_resolver_returns(host):
    # A resolver that reads them the way Linux does (V42, U24) answers 127.0.0.1
    with pytest.raises(AddressRefused, match="private, local or reserved"):
        _vet(host, {host: ["127.0.0.1"]})


@pytest.mark.parametrize("failure", [OSError("no such host"), UnicodeError("bad"), ValueError("x")])
def test_any_resolver_error_refuses(failure):
    with pytest.raises(AddressRefused, match="could not be looked up"):
        _vet("x.test", {"x.test": failure})


def test_an_empty_answer_refuses():
    with pytest.raises(AddressRefused, match="could not be looked up"):
        _vet("x.test", {"x.test": []})


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_the_real_resolver_refuses_localhost_and_loopback(host):
    # The test guard allows only loopback lookups, so this never leaves the computer
    with pytest.raises(AddressRefused, match="private, local or reserved"):
        asyncio.run(vet_host(host, 80))
