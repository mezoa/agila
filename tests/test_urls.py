import pytest

from agila.urls import UrlError, check_url, normalize_url

# (given, normalized): the PRD rules (FR7)
RULES = [
    ("HTTP://EXAMPLE.COM/Path", "http://example.com/Path"),  # scheme and host lowercase
    ("https://Example.Com/a/b#section-2", "https://example.com/a/b"),  # fragment dropped
    ("https://example.com/a?utm_source=x&id=7", "https://example.com/a?id=7"),
    ("https://example.com/a?UTM_Medium=x&q=a", "https://example.com/a?q=a"),  # case-insensitive
    ("https://example.com/a?fbclid=1&gclid=2&q=a", "https://example.com/a?q=a"),
    ("https://example.com/a?FBCLID=1&GCLID=2&q=a", "https://example.com/a?q=a"),
    ("https://example.com/a?utm_source=x&utm_medium=y", "https://example.com/a"),  # no bare "?"
    ("https://example.com/a?z=1&a=2&m=3", "https://example.com/a?z=1&a=2&m=3"),  # order kept
    ("https://example.com/a/b/", "https://example.com/a/b"),  # trailing slash
    ("https://example.com/", "https://example.com"),  # root slash (Q5)
    ("https://example.com", "https://example.com"),
    ("https://example.com/a/?x=1", "https://example.com/a?x=1"),  # slash before a query
    ("https://example.com/a?utm_x=1#frag", "https://example.com/a"),
    ("  https://example.com/a/  ", "https://example.com/a"),  # spaces around the link
]

# Not normalized yet, on purpose (plan, block f part 1, step 2): each one is pinned so a later
# change is a decision, not an accident.
NOT_HANDLED = [
    ("https://example.com/a?b=2&a=1", "https://example.com/a?b=2&a=1"),  # parameter order
    ("https://example.com:80/a", "https://example.com:80/a"),  # default ports untouched
    ("https://example.com:443/a", "https://example.com:443/a"),
    ("https://example.com:8080/a", "https://example.com:8080/a"),
    ("http://example.com/a", "http://example.com/a"),  # http stays http
    ("https://www.example.com/a", "https://www.example.com/a"),  # www kept
    ("https://example.com/a?ref=h&mc_cid=1&igshid=2", "https://example.com/a?ref=h&mc_cid=1&igshid=2"),
    ("https://example.com/a?utm%5Fsource=x", "https://example.com/a?utm%5Fsource=x"),  # encoded
    ("https://example.com/A/b", "https://example.com/A/b"),  # path case kept
    ("https://example.com/%7Euser", "https://example.com/%7Euser"),  # percent-encoding case
    ("https://example.com/%7euser", "https://example.com/%7euser"),
    ("https://bücher.example/a", "https://bücher.example/a"),  # non-ASCII host
    ("https://user:pw@Example.com/a", "https://user:pw@example.com/a"),  # userinfo kept
    ("https://example.com//a//", "https://example.com//a/"),  # only ONE trailing slash goes
    ("https://example.com/index.html", "https://example.com/index.html"),
    ("https://example.com/#!/page", "https://example.com"),  # "#!" route is a fragment
]


@pytest.mark.parametrize(("given", "expected"), RULES)
def test_normalization_rules(given, expected):
    assert normalize_url(given) == expected


@pytest.mark.parametrize(("given", "expected"), NOT_HANDLED)
def test_unhandled_cases_stay_as_they_are(given, expected):
    assert normalize_url(given) == expected


def test_tracking_parameters_do_not_change_the_identity():
    plain = normalize_url("https://example.com/post/1")
    tracked = normalize_url("HTTPS://Example.com/post/1/?utm_source=a&fbclid=z#top")
    assert plain == tracked


def test_normalizing_twice_changes_nothing():
    once = normalize_url("HTTP://Example.com/a/?utm_x=1&b=2#f")
    assert normalize_url(once) == once


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///C:/notes.txt",
        "javascript:alert(1)",
        "mailto:someone@example.com",
        "htp://example.com",  # typo in the scheme
        "http//example.com",  # missing colon
        "example.com",  # no scheme
        "www.example.com/a",
        "",
        "   ",
        "http://",
        "https:///path",
        "http://example.com:notaport/a",
        "http://[::1/a",  # broken IPv6 bracket
    ],
)
def test_bad_links_are_refused_with_one_sentence(url):
    with pytest.raises(UrlError) as err:
        check_url(url)
    assert str(err.value).count("\n") == 0
    assert len(str(err.value).replace(url.strip(), "").split()) <= 25  # one short sentence


def test_normalize_refuses_bad_links_too():
    with pytest.raises(UrlError):
        normalize_url("ftp://example.com")


@pytest.mark.parametrize("url", ["http://example.com", "HTTPS://EXAMPLE.COM/a", "http://localhost"])
def test_http_and_https_pass_the_scheme_check(url):
    # localhost passes here on purpose: the private-address block is Day 5 (U21)
    assert check_url(url) == url
