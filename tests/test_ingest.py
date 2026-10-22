import contextlib
import io
from datetime import datetime

import numpy as np
import pytest

from agila import db, ingest, library, netcheck
from agila.chunking import CACHE_DIR


def test_missing_markdown_file_prints_one_sentence(tmp_path, capsys):
    code = ingest.main(["markdown", str(tmp_path / "nope.md")])
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("File not found:")
    assert "Traceback" not in out


def test_missing_text_file_prints_one_sentence(tmp_path, capsys):
    code = ingest.main(["text", "--title", "T", "--label", "L", "--file", str(tmp_path / "x.txt")])
    assert code == 1
    assert capsys.readouterr().out.startswith("File not found:")


def test_missing_variable_is_named_without_a_traceback(tmp_path, monkeypatch, capsys):
    note = tmp_path / "n.md"
    note.write_text("# Hi\nSome text.", encoding="utf-8")
    for name in db.ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    code = ingest.main(["markdown", str(note)])
    out = capsys.readouterr().out
    assert code == 1
    assert "POSTGRES_HOST" in out
    assert "Traceback" not in out


def test_text_command_needs_title_and_label():
    with pytest.raises(SystemExit):
        ingest.main(["text", "--title", "T"])


# --- ingest url (block f part 2): no database and no network are used in these tests ---


def _no_database():
    return contextlib.nullcontext(None)  # save_url refuses before it would touch the connection


def test_url_command_refuses_a_typo_link_with_one_sentence(capsys):
    code = ingest.main(["url", "htp://example.test/a"], connect=_no_database)
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("Only http and https links")
    assert "Traceback" not in out


def test_url_command_refuses_localhost_with_one_sentence(capsys):
    code = ingest.main(["url", "http://localhost:8000/"], connect=_no_database)
    out = capsys.readouterr().out
    assert code == 1
    assert "private, local or reserved" in out
    assert "Traceback" not in out


def test_url_command_refuses_the_cloud_metadata_address(monkeypatch, capsys):
    async def numeric_only(host, port):  # what the system gives for a numeric address
        return [host]

    monkeypatch.setattr(netcheck, "system_resolver", numeric_only)
    code = ingest.main(["url", "http://169.254.169.254/latest/meta-data"], connect=_no_database)
    out = capsys.readouterr().out
    assert code == 1
    assert "private, local or reserved" in out
    assert "Traceback" not in out


def test_url_command_prints_the_stored_title(monkeypatch, capsys):
    calls = []

    def fake_save(conn, url, title=None, replace=False):
        calls.append((url, title, replace))
        return library.Saved(1, 4, "The page title")

    monkeypatch.setattr(ingest, "save_url", fake_save)
    code = ingest.main(["url", "https://example.test/a", "--title", "Mine"], connect=_no_database)
    assert code == 0
    assert calls == [("https://example.test/a", "Mine", False)]
    assert capsys.readouterr().out == "Saved The page title: 4 chunks\n"


# --- block g: list, archive, unarchive, delete and --replace ---

needs_model = pytest.mark.skipif(
    not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed"
)


class FakeEmbedder:
    def passage_embed(self, texts):
        return (np.full(384, i, dtype=np.float32) for i in range(len(texts)))


def _test_database(empty_db):
    return lambda: db.connect(dbname=empty_db)  # the throwaway agila_test, never agila


@pytest.mark.db
@needs_model
def test_list_command_prints_title_date_status_and_visibility(conn, empty_db, capsys):
    kept = library.save_text(conn, "Kept note", "k", "Some kept text.", FakeEmbedder())
    library.save_text(conn, "Active note", "a", "Some active text.", FakeEmbedder())
    library.archive(conn, kept.document_id)
    conn.commit()
    assert ingest.main(["list"], connect=_test_database(empty_db)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    for line, title, status in zip(
        lines, ("Active note", "Kept note"), ("active", "archived"), strict=True
    ):
        assert (title in line, today in line, status in line, "anywhere" in line) == (
            True, True, True, True
        )


def test_list_command_on_an_empty_library_prints_one_sentence(monkeypatch, capsys):
    monkeypatch.setattr(ingest, "list_documents", lambda conn: [])
    assert ingest.main(["list"], connect=_no_database) == 0
    assert capsys.readouterr().out == "No documents saved yet.\n"


@pytest.mark.db
@needs_model
def test_delete_without_yes_deletes_nothing(conn, empty_db, capsys):
    saved = library.save_text(conn, "My note", "n", "Some text.", FakeEmbedder())
    conn.commit()
    assert ingest.main(["delete", str(saved.document_id)], connect=_test_database(empty_db)) == 0
    out = capsys.readouterr().out
    assert out.startswith(f'Would delete document {saved.document_id} "My note" (text, saved ')
    assert "1 chunks). Nothing deleted. Run again with --yes" in out
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


@pytest.mark.db
@needs_model
def test_delete_with_yes_prints_the_title_and_chunk_count(conn, empty_db, capsys):
    saved = library.save_text(conn, "My note", "n", "Some text.", FakeEmbedder())
    conn.commit()
    code = ingest.main(
        ["delete", str(saved.document_id), "--yes"], connect=_test_database(empty_db)
    )
    assert code == 0
    assert capsys.readouterr().out == (
        f'Deleted document {saved.document_id} "My note" and its 1 chunks.\n'
    )
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


@pytest.mark.db
def test_delete_of_an_unknown_id_prints_one_sentence(conn, empty_db, capsys):
    for argv in (["delete", "999999"], ["delete", "999999", "--yes"], ["archive", "999999"]):
        assert ingest.main(argv, connect=_test_database(empty_db)) == 1
        assert capsys.readouterr().out == "No document with id 999999.\n"


@pytest.mark.parametrize("bad", ["abc", "0", "-3", str(2**63)])
def test_a_document_id_must_be_a_whole_number(bad):
    with pytest.raises(SystemExit):
        ingest.main(["delete", bad], connect=_no_database)


@pytest.mark.parametrize(
    ("argv", "name"),
    [
        (["text", "--title", "T", "--label", "L", "--replace"], "save_text"),
        (["markdown", "NOTE", "--replace"], "save_markdown"),
        (["url", "https://example.test/a", "--replace"], "save_url"),
    ],
)
def test_replace_flag_reaches_the_library(argv, name, tmp_path, monkeypatch, capsys):
    note = tmp_path / "n.md"
    note.write_text("# Hi\nSome text.", encoding="utf-8")
    argv = [str(note) if a == "NOTE" else a for a in argv]
    monkeypatch.setattr("sys.stdin", io.StringIO("Some text."))
    calls = []

    def fake(*args, replace=False, **kwargs):
        calls.append(replace)
        return library.Saved(7, 2, "T", "replaced", (3,))

    monkeypatch.setattr(ingest, name, fake)
    assert ingest.main(argv, connect=_no_database) == 0
    assert calls == [True]
    assert capsys.readouterr().out.endswith(". It replaces document 3, now superseded.\n")


def test_a_label_warning_is_printed_on_its_own_line(monkeypatch, capsys):
    warning = 'Warning: a different note labelled L is already saved as document 1 "Old"'
    monkeypatch.setattr(
        ingest, "save_text", lambda *a, **k: library.Saved(2, 1, "T", warning=warning)
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("Some text."))
    assert ingest.main(["text", "--title", "T", "--label", "L"], connect=_no_database) == 0
    assert capsys.readouterr().out == f"Saved T: 1 chunks\n{warning}\n"
