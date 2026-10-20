import asyncio
import time
from pathlib import Path

import httpx
import pytest

from agila.web import (
    FetchError,
    PageRejected,
    check_text,
    count_sentences,
    extract_page,
    fetch_html,
    fetch_html_async,
)

FIXTURES = Path(__file__).parent / "fixtures"
URL = "http://example.test/page"


def _transport(handler):
    return httpx.MockTransport(handler)


# --- the download, through httpx.MockTransport (no network, no server) ---


def test_200_returns_the_body_text():
    transport = _transport(lambda request: httpx.Response(200, text="<p>hello</p>"))
    assert fetch_html(URL, transport=transport) == "<p>hello</p>"


@pytest.mark.parametrize("status", [403, 404, 500])
def test_other_statuses_name_the_status(status):
    transport = _transport(lambda request: httpx.Response(status, text="no"))
    with pytest.raises(FetchError, match=f"status {status}"):
        fetch_html(URL, transport=transport)


def test_a_redirect_is_refused_until_day_5():
    transport = _transport(lambda request: httpx.Response(301, headers={"Location": "/elsewhere"}))
    with pytest.raises(FetchError, match="redirects are not supported yet"):
        fetch_html(URL, transport=transport)


def test_connection_error_is_one_readable_sentence():
    def refuse(request):
        raise httpx.ConnectError("boom with details", request=request)

    with pytest.raises(FetchError) as err:
        fetch_html(URL, transport=_transport(refuse))
    assert str(err.value).startswith("Could not connect")
    assert "boom" not in str(err.value)  # no raw library text


def test_any_other_http_error_is_readable_too():
    def broken(request):
        raise httpx.ReadError("connection reset", request=request)

    with pytest.raises(FetchError, match="could not be downloaded"):
        fetch_html(URL, transport=_transport(broken))


def test_total_time_limit_cancels_a_stalled_answer():
    async def stall(request):
        await asyncio.sleep(5)
        return httpx.Response(200, text="too late")

    started = time.perf_counter()
    with pytest.raises(FetchError, match=r"longer than 0\.2 seconds"):
        fetch_html(URL, timeout=0.2, transport=_transport(stall))
    assert time.perf_counter() - started < 1.5  # about 0.2 s, not 5 s


def test_fetch_html_refuses_to_run_inside_an_event_loop():
    transport = _transport(lambda request: httpx.Response(200, text="x"))

    async def caller():
        return fetch_html(URL, transport=transport)

    with pytest.raises(FetchError, match="event loop"):
        asyncio.run(caller())


def test_async_version_works_inside_an_event_loop():
    transport = _transport(lambda request: httpx.Response(200, text="async body"))
    assert asyncio.run(fetch_html_async(URL, transport=transport)) == "async body"


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
