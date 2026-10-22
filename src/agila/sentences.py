"""The one sentence rule [assumed, FR2], shared by the 3-sentence page check and the answer quotes.

Cut at ".", "!" or "?" followed by whitespace, and at line breaks, but not after an abbreviation
such as "e.g."; "3.5" has no space after the dot, so it never splits. A piece of fewer than 3
words is joined to the piece before it (or after it, at the start), so a menu line like "Home"
never counts. Known gaps (research U35): "etc.", "No.", "Jan." and "(e.g." do split.
"""

import re

MIN_WORDS_PER_SENTENCE = 3

# Words before a full stop that do not end a sentence. "etc." is left out: it often does.
ABBREVIATIONS = {"e.g.", "i.e.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.", "fig.", "approx."}
DOTTED_INITIALS = re.compile(r"^(?:[a-z]\.){2,}$")  # u.s. , a.m.
BREAK = re.compile(r"(?P<end>[.!?]+)\s+|\n+")


def _units(text: str) -> tuple[list[str], str]:
    """The sentences, plus any leftover text of fewer than 3 words (only when there are none)."""
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
    return units, carry


def count_sentences(text: str) -> int:
    """FR2: the number of sentences; a text of fewer than 3 words counts 0."""
    return len(_units(text)[0])


def split_sentences(text: str) -> list[str]:
    """The numbered sentences of a chunk: sentence n is `split_sentences(text)[n - 1]`.

    Same cuts as `count_sentences`, but a text of fewer than 3 words is one sentence (not none),
    so every non-blank chunk has at least sentence 1. Used for the prompt and for the quote.
    """
    units, carry = _units(text)
    return units + [carry] if carry else units
