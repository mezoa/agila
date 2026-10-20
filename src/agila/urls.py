"""Check that a link is http or https and build its normalized form (FR2 scheme rule, FR7 key)."""

from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("http", "https")
TRACKING_NAMES = ("fbclid", "gclid")
TRACKING_PREFIX = "utm_"


class UrlError(ValueError):
    """A link that cannot be saved; the message is one readable sentence."""


def check_url(url: str) -> str:
    """Return the link without surrounding spaces, or raise UrlError."""
    url = url.strip()
    if not url:
        raise UrlError("The link is empty. Give a full link that starts with http:// or https://.")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018  # raises ValueError for a bad port
    except ValueError:
        raise UrlError(f"This is not a valid link: {url}") from None
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlError(f"Only http and https links can be saved, and {url} is neither.")
    if not host:
        raise UrlError(f"The link has no host name: {url}")
    return url


def _is_tracking(piece: str) -> bool:
    name = piece.split("=", 1)[0].lower()
    return name.startswith(TRACKING_PREFIX) or name in TRACKING_NAMES


def normalize_url(url: str) -> str:
    """The identity form of a web link (PRD FR7, rules only).

    Lowercase scheme and host; no fragment; no utm_*, fbclid or gclid parameters (names compared
    ignoring case); no trailing slash on the path. Nothing else changes: path case, parameter
    order, "www.", http versus https and ports are kept (see the plan for what is not handled).
    """
    parts = urlsplit(check_url(url))
    userinfo, at, hostport = parts.netloc.rpartition("@")
    netloc = userinfo + at + hostport.lower()
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    query = "&".join(p for p in parts.query.split("&") if not _is_tracking(p))
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
