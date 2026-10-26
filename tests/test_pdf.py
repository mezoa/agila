import ast
import io
import logging
import warnings
from pathlib import Path

import pytest
from pdfs import locked_pdf, text_pdf
from pypdf import PageObject, PdfReader
from pypdf.errors import DependencyError

from agila import pdf
from agila.pdf import PdfError, clean_page, read_pdf


def _texts(data: bytes) -> list[str]:
    return [(page.extract_text() or "").strip() for page in PdfReader(io.BytesIO(data)).pages]


def test_the_helper_pdf_reads_back_page_by_page():
    data = text_pdf(["Alpha one.\nSecond line.", "", "Gamma (three)."])
    assert _texts(data) == ["Alpha one.\nSecond line.", "", "Gamma (three)."]


def test_a_locked_helper_pdf_needs_its_password():
    reader = PdfReader(io.BytesIO(locked_pdf(text_pdf(["Secret words here."]))))
    assert reader.is_encrypted
    assert reader.decrypt("pw")
    assert reader.pages[0].extract_text().strip() == "Secret words here."


def test_an_empty_user_password_opens_without_decrypt():
    reader = PdfReader(io.BytesIO(locked_pdf(text_pdf(["Open words here."]), user_password="")))
    assert reader.is_encrypted
    assert reader.pages[0].extract_text().strip() == "Open words here."


# Step 4: cleaning (pure)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("ﬁle and ofﬂine", "file and offline"),
        ("infor-\nmation", "information"),
        ("infor- \n mation", "information"),  # spaces next to a hyphen break
        ("one\n \nword\n\t\nper line", "one word per line"),  # space-only lines (the thesis)
        ("para one \n\n para two", "para one\n\npara two"),  # a truly empty line stays
        ("from 2020-\n21", "from 2020- 21"),
        ("a  \t b", "a b"),
        ("one\nword\nper\nline", "one word per line"),
        ("end of line \n next", "end of line next"),
        ("para one\n\npara two", "para one\n\npara two"),
        ("one\n\n\n\ntwo", "one\n\ntwo"),
        ("   \n  \t ", ""),
    ],
)
def test_clean_page(raw, clean):
    assert clean_page(raw) == clean


# Step 5: reading and refusing


def _file(tmp_path, data: bytes, name: str = "doc.pdf"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


GOOD = ["Alpha page one has words. " * 3, "", "Gamma page three has words. " * 3]


def test_read_pdf_gives_one_cleaned_string_per_page(tmp_path):
    # 93 + 0 + 91 characters after joining: a mean of 61, over the 50 rule
    alpha = (
        "Alpha page one starts here, and it goes on to\n"
        "a second line that holds more of its own words."
    )
    gamma = (
        "Gamma page three has a first line, and then it\n"
        "has one more line that holds the rest of it."
    )
    pages = read_pdf(_file(tmp_path, text_pdf([alpha, "", gamma])))
    assert pages == [alpha.replace("\n", " "), "", gamma.replace("\n", " ")]


def test_the_50_rule_counts_the_mean_of_cleaned_characters(tmp_path):
    assert read_pdf(_file(tmp_path, text_pdf(["x" * 100, ""]))) == ["x" * 100, ""]
    with pytest.raises(PdfError, match="looks scanned or empty"):
        read_pdf(_file(tmp_path, text_pdf(["x" * 98, ""])))


def test_an_owner_only_lock_with_an_empty_user_password_is_read(tmp_path):
    data = locked_pdf(text_pdf(GOOD), user_password="")
    assert read_pdf(_file(tmp_path, data))[2].startswith("Gamma page three")


def _refusals(tmp_path) -> dict[str, tuple[object, str]]:
    """Each refused case: (file, the words its sentence must contain)."""
    good = text_pdf(GOOD)
    return {
        "missing": (tmp_path / "missing.pdf", "File not found"),
        "scanned": (_file(tmp_path, text_pdf(["", ""]), "scan.pdf"), "looks scanned or empty"),
        "zero bytes": (_file(tmp_path, b"", "zero.pdf"), "looks scanned or empty"),
        "zero pages": (_file(tmp_path, text_pdf([]), "nopages.pdf"), "looks scanned or empty"),
        "not a pdf": (_file(tmp_path, b"plain text here\n" * 10, "notes.pdf"), "is not a PDF"),
        "damaged": (_file(tmp_path, good[: len(good) // 2], "half.pdf"), "looks damaged"),
        "password": (_file(tmp_path, locked_pdf(good), "locked.pdf"), "password-protected"),
    }


@pytest.mark.parametrize(
    "case", ["missing", "scanned", "zero bytes", "zero pages", "not a pdf", "damaged", "password"]
)
def test_each_refusal_is_one_short_sentence_naming_the_file(tmp_path, case):
    path, words = _refusals(tmp_path)[case]
    with pytest.raises(PdfError) as caught:
        read_pdf(path)
    message = str(caught.value)
    assert words in message
    assert path.name in message
    assert len(message.split()) <= 25
    if case != "missing":  # "File not found: <path>", the same words as save_markdown
        assert message.endswith(".")


def test_an_aes_lock_without_cryptography_is_refused_as_locked(tmp_path, monkeypatch):
    def needs_cryptography(path):
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(pdf, "PdfReader", needs_cryptography)
    with pytest.raises(PdfError, match="aes.pdf is password-protected or locked"):
        read_pdf(_file(tmp_path, text_pdf(GOOD), "aes.pdf"))


def test_a_file_over_the_size_cap_is_refused_before_it_is_opened(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(pdf, "MAX_BYTES", 100)
    monkeypatch.setattr(pdf, "PdfReader", lambda path: opened.append(path))
    with pytest.raises(PdfError, match=r"^big.pdf is over 50 MB"):
        read_pdf(_file(tmp_path, text_pdf(GOOD), "big.pdf"))
    assert opened == []


def test_too_many_pages_is_refused_before_any_text_is_extracted(tmp_path, monkeypatch):
    extracted = []
    monkeypatch.setattr(pdf, "MAX_PAGES", 2)
    monkeypatch.setattr(PageObject, "extract_text", lambda self, *a, **k: extracted.append(1))
    with pytest.raises(PdfError, match=r"^long.pdf has 3 pages, more than 2; split it"):
        read_pdf(_file(tmp_path, text_pdf(GOOD), "long.pdf"))
    assert extracted == []


def test_only_pdf_py_imports_pypdf():
    for path in Path(pdf.__file__).parent.glob("*.py"):
        if path.name == "pdf.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(n.split(".")[0] == "pypdf" for n in names), path.name


def test_pypdf_log_lines_and_warnings_are_hidden_while_reading(tmp_path, monkeypatch, caplog):
    def noisy_reader(path):
        warnings.warn("a pypdf-style warning", UserWarning, stacklevel=1)
        logging.getLogger("pypdf._reader").warning("EOF marker not found")
        raise ValueError("broken")

    level = logging.getLogger("pypdf").level
    monkeypatch.setattr(pdf, "PdfReader", noisy_reader)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with pytest.raises(PdfError, match="noisy.pdf looks damaged"):
            read_pdf(_file(tmp_path, text_pdf(GOOD), "noisy.pdf"))
    assert seen == []
    assert caplog.records == []
    assert logging.getLogger("pypdf").level == level  # restored afterwards


@pytest.mark.parametrize("error", [ValueError("bad number"), KeyError("/Root")])
def test_any_error_inside_pypdf_becomes_the_damaged_sentence(tmp_path, monkeypatch, error):
    def broken_reader(path):
        raise error

    monkeypatch.setattr(pdf, "PdfReader", broken_reader)
    with pytest.raises(PdfError) as caught:
        read_pdf(_file(tmp_path, text_pdf(GOOD), "odd.pdf"))
    assert str(caught.value) == (
        "odd.pdf looks damaged and could not be read; re-export it and try again."
    )
