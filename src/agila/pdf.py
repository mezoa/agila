"""Read a text PDF page by page and clean each page (FR3). The only module that imports pypdf.

`read_pdf` returns one cleaned string per PDF page, blank pages kept as "" so a list index + 1
is always the PDF page number. Every refusal is a `PdfError` with one sentence naming the file.
Checks run in this order: file exists, size, `%PDF-` header, password, page count, extraction,
then the mean of 50 cleaned characters per page. Size and pages are checked before any text is
extracted. Caps and the 50 rule are [assumed] (FR3, research U61). While a file is read, pypdf's
own log lines and Python warnings are hidden, so the CLI prints only the one sentence (NFR7).
"""

import logging
import re
import unicodedata
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pypdf import PasswordType, PdfReader
from pypdf.errors import DependencyError, EmptyFileError, FileNotDecryptedError

MAX_BYTES = 50 * 1024 * 1024  # 50 MiB [assumed]
MAX_PAGES = 300  # [assumed]
MIN_MEAN_CHARACTERS = 50  # FR3 [assumed]

SPACES = re.compile(r"[ \t]+")
AROUND_BREAK = re.compile(r" ?\n ?")
# letters on both sides (not "2020-\n21"); spaces next to the break are allowed
HYPHEN_BREAK = re.compile(r"([^\W\d_])-[ \t]*\n[ \t]*([^\W\d_])")
# every line break that is not part of "\n\n", so "\n \n" (a space-only line) is two of them
SINGLE_BREAK = re.compile(r"(?<!\n)\n(?!\n)")
MANY_BREAKS = re.compile(r"\n{3,}")


class PdfError(Exception):
    """A PDF that cannot be saved; the message is one readable sentence."""


def clean_page(text: str) -> str:
    """NFKC (ligatures), join hyphenated line breaks, every single line break becomes a space
    (also one followed by a space-only line), then collapse spaces. Only a truly empty line
    stays a paragraph break (research V103 to V105). Single breaks go BEFORE the spaces are
    trimmed: the thesis has 15,423 space-only lines between words (lesson 2026-10-26)."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n")
    text = HYPHEN_BREAK.sub(r"\1\2", text)
    text = SINGLE_BREAK.sub(" ", text)
    text = AROUND_BREAK.sub("\n", SPACES.sub(" ", text))
    return MANY_BREAKS.sub("\n\n", text).strip()


def _scanned(name: str) -> PdfError:
    return PdfError(
        f"{name} has almost no text (it looks scanned or empty); Agila saves text PDFs only."
    )


def _locked(name: str) -> PdfError:
    return PdfError(
        f"{name} is password-protected or locked; remove the protection and save it again."
    )


def _damaged(name: str) -> PdfError:
    return PdfError(f"{name} looks damaged and could not be read; re-export it and try again.")


@contextmanager
def _quiet() -> Iterator[None]:
    """Hide the "pypdf" logger (its child loggers inherit the level) and Python warnings."""
    logger = logging.getLogger("pypdf")
    level = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        logger.setLevel(level)


def _step[T](name: str, call: Callable[[], T]) -> T:
    """One pypdf call; any error it raises becomes one sentence, never a stack trace."""
    try:
        return call()
    except (DependencyError, FileNotDecryptedError):  # AES needs `cryptography` (V107)
        raise _locked(name) from None
    except EmptyFileError:
        raise _scanned(name) from None
    except Exception:  # pypdf's own errors, and anything else a broken file sets off inside it
        raise _damaged(name) from None


def read_pdf(path: Path) -> list[str]:
    """The cleaned text of every page, in page order, or a `PdfError`."""
    path = Path(path)
    name = path.name
    if not path.is_file():
        raise PdfError(f"File not found: {path}")
    if path.stat().st_size > MAX_BYTES:
        raise PdfError(f"{name} is over 50 MB; save a smaller PDF or split it.")
    with path.open("rb") as file:
        head = file.read(5)
    if not head:
        raise _scanned(name)
    if head != b"%PDF-":
        raise PdfError(f"{name} is not a PDF; save a text-based PDF file.")

    with _quiet():
        reader = _step(name, lambda: PdfReader(path))
        if _step(
            name, lambda: reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED
        ):
            raise _locked(name)
        count = _step(name, lambda: len(reader.pages))
        if count == 0:
            raise _scanned(name)
        if count > MAX_PAGES:
            raise PdfError(
                f"{name} has {count} pages, more than {MAX_PAGES}; split it and save the parts."
            )
        pages = [
            clean_page(_step(name, lambda i=i: reader.pages[i].extract_text()) or "")
            for i in range(count)
        ]

    if sum(len(page) for page in pages) / len(pages) < MIN_MEAN_CHARACTERS:
        raise _scanned(name)
    return pages
