from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import real_vault_names, vault_difference

from agila import export
from agila.export import Doc, Part, local_date, note_name, pdf_name, render_note, safe_title

SAVED = datetime(2026, 10, 27, 3, 15, tzinfo=UTC)


# --- the session guard on the real raw/agila (conftest, block n step 6 lesson) ---


def test_the_guard_passes_when_the_real_vault_names_are_the_same():
    assert vault_difference(set(), set()) is None
    assert (
        vault_difference({"A (1).md", "files/A (1).pdf"}, {"A (1).md", "files/A (1).pdf"}) is None
    )


def test_the_guard_names_what_was_added_and_removed():
    problem = vault_difference({"A (1).md", "B (2).md"}, {"A (1).md", "Note (9).md"})
    assert "added ['Note (9).md']" in problem
    assert "removed ['B (2).md']" in problem


def test_the_guard_lists_file_names_or_nothing(tmp_path):
    assert real_vault_names(tmp_path / "missing") == set()
    (tmp_path / "files").mkdir()
    (tmp_path / "A (1).md").write_text("a", encoding="utf-8")
    (tmp_path / "files" / "A (1).pdf").write_bytes(b"%PDF")
    assert real_vault_names(tmp_path) == {"A (1).md", "files/A (1).pdf"}


def test_every_test_exports_into_a_temporary_vault(vault, tmp_path):
    assert export.vault_dir() == vault
    assert export.vault_dir().is_relative_to(tmp_path)


def test_the_default_vault_is_raw_agila_in_the_project_folder(monkeypatch):
    monkeypatch.delenv("VAULT_PATH")
    project = Path(export.__file__).resolve().parents[2]
    assert export.vault_dir() == project / "raw" / "agila"


# --- file names (step 4) ---


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("a:b", "a-b"),
        ('x<y>z"w/v\\u|t?s*r', "x-y-z-w-v-u-t-s-r"),
        ("x?*", "x"),
        ("#tag [x] ^y 50%", "tag -x- -y 50"),
        ("ﬁle", "file"),
        ("Report.", "Report"),
        ("  spaced   out \t title  ", "spaced out - title"),
        ("   ", "untitled"),
        ("...", "untitled"),
        ("line\nbreak", "line-break"),
    ],
)
def test_safe_title_replaces_unsafe_characters(title, expected):
    assert safe_title(title) == expected


def test_safe_title_keeps_80_characters():
    assert safe_title("a" * 100) == "a" * 80


def test_a_cut_that_ends_in_a_space_or_dot_is_stripped():
    assert safe_title("a" * 78 + " .b") == "a" * 78
    assert safe_title("a" * 79 + ".b") == "a" * 79


def test_a_reserved_windows_name_is_never_the_whole_file_name():
    assert note_name("CON", 3) == "CON (3).md"
    assert pdf_name("NUL", 4) == "NUL (4).pdf"


def test_titles_that_differ_only_in_case_still_get_different_names():
    first, second = note_name("Notes", 1), note_name("NOTES", 2)
    assert first.lower() != second.lower()


# --- the note text (step 4) ---


def _doc(source_type="text", **changes):
    values = dict(
        document_id=7,
        title="My note",
        source_type=source_type,
        source_label="my-label",
        source_url=None,
        saved_at=SAVED,
        status="active",
    )
    return Doc(**(values | changes))


def test_a_text_note_has_the_properties_then_the_chunks_in_order():
    note = render_note(_doc(), [Part("First chunk."), Part("Second chunk.")])
    assert note == (
        "---\n"
        'title: "My note"\n'
        'source: "my-label"\n'
        f"saved: {local_date(SAVED)}\n"
        "status: active\n"
        "tags:\n"
        "  - agila\n"
        "  - agila/text\n"
        "agila_id: 7\n"
        "type: text\n"
        "---\n"
        "\n"
        "First chunk.\n"
        "\n"
        "Second chunk.\n"
    )


def test_a_web_note_names_the_original_link_as_its_source():
    doc = _doc(
        "web", source_label="https://example.test/a", source_url="https://Example.test/a?x=1"
    )
    note = render_note(doc, [Part("Body.")])
    assert 'source: "https://Example.test/a?x=1"\n' in note
    assert "  - agila/web\n" in note
    assert "type: web\n" in note


def test_the_status_line_follows_the_document():
    for status in ("active", "archived", "superseded"):
        assert f"status: {status}\n" in render_note(_doc(status=status), [Part("x")])


def test_a_markdown_note_writes_each_heading_once_when_it_changes():
    parts = [Part("Intro."), Part("One.", "Setup"), Part("Two.", "Setup"), Part("Three.", "Use")]
    body = render_note(_doc("markdown"), parts).split("---\n\n", 1)[1]
    assert body == "Intro.\n\n## Setup\n\nOne.\n\nTwo.\n\n## Use\n\nThree.\n"


def test_a_pdf_note_marks_each_page_and_skips_pages_without_chunks():
    parts = [Part("Page one a.", page=1), Part("Page one b.", page=1), Part("Page three.", page=3)]
    note = render_note(_doc("pdf", page_count=3), parts)
    assert "type: pdf\npages: 3\n---\n" in note
    body = note.split("---\n\n", 1)[1]
    assert body == (
        "**PDF page 1**\n\nPage one a.\n\nPage one b.\n\n**PDF page 3**\n\nPage three.\n"
    )
    assert "PDF page 2" not in note


def test_pages_is_written_for_pdfs_only():
    assert "pages:" not in render_note(_doc(), [Part("x")])


def test_awkward_titles_are_written_as_json_strings():
    note = render_note(_doc(title='Colon: "quoted" #hash \\ ✅'), [Part("x")])
    assert 'title: "Colon: \\"quoted\\" #hash \\\\ ✅"\n' in note


def test_the_saved_date_is_the_local_date_of_saved_at():
    assert f"saved: {local_date(SAVED)}\n" in render_note(_doc(), [Part("x")])
    assert local_date(SAVED) == SAVED.astimezone().strftime("%Y-%m-%d")


# --- writing, copying and deleting files (step 5) ---


def _names(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def test_write_note_creates_the_note_and_leaves_no_temporary_file(vault):
    export.write_note(7, "My note (7).md", "Hello ✅\n")
    assert (vault / "My note (7).md").read_bytes() == "Hello ✅\n".encode()
    assert _names(vault) == ["My note (7).md"]


def test_writing_again_replaces_the_note(vault):
    export.write_note(7, "My note (7).md", "old\n")
    export.write_note(7, "My note (7).md", "new\n")
    assert (vault / "My note (7).md").read_text(encoding="utf-8") == "new\n"
    assert _names(vault) == ["My note (7).md"]


def test_a_stale_temporary_file_is_simply_overwritten(vault):
    vault.mkdir(parents=True)
    (vault / ".7.md.tmp").write_bytes(b"left over from a crash, longer than the new text")
    export.write_note(7, "My note (7).md", "new\n")
    assert (vault / "My note (7).md").read_text(encoding="utf-8") == "new\n"
    assert _names(vault) == ["My note (7).md"]


def _flaky_replace(monkeypatch, failures):
    """os.replace raises PermissionError `failures` times, then works; sleeps are recorded."""
    real, calls, sleeps = export.os.replace, [], []

    def replace(src, dst):
        calls.append(dst)
        if len(calls) <= failures:
            raise PermissionError(13, "in use")
        real(src, dst)

    monkeypatch.setattr(export.os, "replace", replace)
    monkeypatch.setattr(export.time, "sleep", sleeps.append)
    return calls, sleeps


def test_a_note_held_open_twice_is_written_on_the_third_try(vault, monkeypatch):
    calls, sleeps = _flaky_replace(monkeypatch, failures=2)
    export.write_note(7, "My note (7).md", "text\n")
    assert len(calls) == 3
    assert sleeps == [export.REPLACE_WAIT, export.REPLACE_WAIT]
    assert (vault / "My note (7).md").read_text(encoding="utf-8") == "text\n"


def test_a_note_held_open_three_times_gives_one_sentence(vault, monkeypatch):
    calls, _ = _flaky_replace(monkeypatch, failures=3)
    with pytest.raises(export.ExportError) as caught:
        export.write_note(7, "My note (7).md", "text\n")
    assert len(calls) == 3
    assert str(caught.value) == (
        "Could not replace My note (7).md; another program may have it open."
    )
    assert not (vault / "My note (7).md").exists()


def test_copy_pdf_copies_the_bytes_and_leaves_the_source_alone(vault, tmp_path):
    source = tmp_path / "manual.pdf"
    data = b"%PDF-1.4\n" + bytes(range(256)) * 9000  # more than one read block
    source.write_bytes(data)
    before = source.stat().st_mtime_ns
    export.copy_pdf(12, source, "manual (12).pdf")
    assert (vault / "files" / "manual (12).pdf").read_bytes() == data
    assert source.read_bytes() == data
    assert source.stat().st_mtime_ns == before
    assert _names(vault) == ["files/manual (12).pdf"]


def test_a_missing_source_pdf_gives_one_sentence_naming_it(vault, tmp_path):
    source = tmp_path / "moved.pdf"
    with pytest.raises(export.ExportError) as caught:
        export.copy_pdf(12, source, "moved (12).pdf")
    assert str(caught.value) == (
        f"The original PDF is no longer at {source}; save it again with pdf PATH."
    )


def test_delete_files_removes_them_and_a_missing_one_is_fine(vault):
    export.write_note(7, "A (7).md", "a\n")
    export.write_note(8, "B (8).md", "b\n")
    assert export.delete_files(["A (7).md", "files/gone (7).pdf"]) == []
    assert _names(vault) == ["B (8).md"]


def test_delete_files_returns_the_names_it_could_not_remove(vault, monkeypatch):
    export.write_note(7, "A (7).md", "a\n")
    export.write_note(8, "B (8).md", "b\n")
    real = Path.unlink

    def unlink(path, missing_ok=False):
        if path.name == "A (7).md":
            raise PermissionError(13, "in use")
        real(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert export.delete_files(["A (7).md", "B (8).md"]) == ["A (7).md"]
    assert _names(vault) == ["A (7).md"]


def test_off_turns_the_export_off_for_one_block_only():
    assert export.enabled()
    with export.off():
        assert not export.enabled()
    assert export.enabled()
    with pytest.raises(RuntimeError), export.off():
        raise RuntimeError("boom")
    assert export.enabled()


@pytest.mark.parametrize(
    "sentence",
    [
        "Could not write My note (7).md (PermissionError).",
        "Could not replace My note (7).md; another program may have it open.",
        "The original PDF is no longer at C:\\Users\\Eo\\Downloads\\manual.pdf;"
        " save it again with pdf PATH.",
        "Could not copy C:\\Users\\Eo\\Downloads\\manual.pdf to files (OSError).",
    ],
)
def test_each_export_sentence_is_short(sentence):
    assert len(sentence.split()) <= 25
    assert sentence.endswith(".")


# --- the export never reads the vault (step 5, decision 9) ---

FORBIDDEN_CALLS = {
    "read_text",
    "read_bytes",
    "iterdir",
    "glob",
    "rglob",
    "listdir",
    "scandir",
    "walk",
    "exists",
    "stat",
    "is_file",
}


def _calls(tree):
    import ast

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            yield node, name


def _open_modes(source: str) -> list[tuple[str, str, str]]:
    """(function, mode, first argument) of every `open(...)` call in the module."""
    import ast

    tree = ast.parse(source)
    found = []
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node, name in _calls(function):
            if name == "open":
                mode = node.args[1].value if len(node.args) > 1 else "r"
                found.append((function.name, mode, ast.unparse(node.args[0])))
    return found


def test_export_calls_no_reading_or_listing_function():
    import ast

    tree = ast.parse(Path(export.__file__).read_text(encoding="utf-8"))
    used = {name for _, name in _calls(tree)}
    assert not used & FORBIDDEN_CALLS


def test_the_only_read_mode_open_is_the_source_pdf_in_copy_pdf():
    opens = _open_modes(Path(export.__file__).read_text(encoding="utf-8"))
    reads = [o for o in opens if o[1] != "wb"]
    assert reads == [("copy_pdf", "rb", "source")]
    assert all(
        mode == "wb" for function, mode, _ in opens if (function, mode) != ("copy_pdf", "rb")
    )


def test_the_open_check_catches_a_read_of_the_vault():
    sneaky = (
        "def write_note(name):\n"
        "    with open(vault_dir() / name, 'r') as f:\n"
        "        return f.read()\n"
        "def copy_pdf(source):\n"
        "    open(source, 'rb')\n"
        "    open(source)\n"
    )
    opens = _open_modes(sneaky)
    assert [o for o in opens if o[1] != "wb"] == [
        ("write_note", "r", "vault_dir() / name"),
        ("copy_pdf", "rb", "source"),
        ("copy_pdf", "r", "source"),
    ]
