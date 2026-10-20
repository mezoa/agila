import pytest

from agila import db, ingest


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
