import contextlib

import pytest

from agila import db, ingest, library, netcheck


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

    def fake_save(conn, url, title=None):
        calls.append((url, title))
        return library.Saved(1, 4, "The page title")

    monkeypatch.setattr(ingest, "save_url", fake_save)
    code = ingest.main(["url", "https://example.test/a", "--title", "Mine"], connect=_no_database)
    assert code == 0
    assert calls == [("https://example.test/a", "Mine")]
    assert capsys.readouterr().out == "Saved The page title: 4 chunks\n"
