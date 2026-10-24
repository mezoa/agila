"""The backup and restore-test scripts (block k, V88 to V90), with a fake docker: no container."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup  # noqa: E402

REAL = backup.REAL_DB
NOW = datetime(2026, 10, 24, 18, 30, 5)
LIBRARY = {"documents": 4, "chunks": 50}


class FakeDocker:
    """Records every command; answers counts, 'copies' a dump file, fails the step it is told."""

    def __init__(self, counts=None, dump_bytes=b"PGDMP\x01fake", fail=None, change_after=None):
        self.counts = counts or {REAL: dict(LIBRARY)}
        self.dump_bytes = dump_bytes
        self.fail = fail
        self.change_after = change_after  # (step, database, new counts)
        self.calls = []

    def __call__(self, args, step):
        self.calls.append((args, step))
        if step == self.fail:
            raise backup.CommandError(f"The {step} step failed (exit code 1).")
        if step.startswith("count "):
            database = re.search(r"-d (\S+) -Atc", args[-1]).group(1)
            return f"{self.counts[database][step.split()[1]]}\n"
        if step == "copy" and args[3].startswith("db:"):
            Path(args[4]).write_bytes(self.dump_bytes)
        if self.change_after and step == self.change_after[0]:
            self.counts[self.change_after[1]] = self.change_after[2]
        return ""

    def steps(self):
        return [step for _, step in self.calls]

    def commands(self):
        return [" ".join(args) for args, _ in self.calls]


# --- backup.py ---


def test_backup_writes_the_dump_and_its_counts_file(tmp_path, capsys):
    docker = FakeDocker()
    assert backup.main(docker, tmp_path, lambda: NOW) == 0
    dump = tmp_path / "agila-20261024-183005.dump"
    assert dump.read_bytes().startswith(b"PGDMP")
    counts = json.loads((tmp_path / "agila-20261024-183005.counts.json").read_text())
    assert counts == LIBRARY
    out = capsys.readouterr().out
    assert "agila-20261024-183005.dump" in out and "documents 4, chunks 50" in out


def test_the_dump_is_written_inside_the_container_and_copied_out(tmp_path):
    docker = FakeDocker()
    backup.main(docker, tmp_path, lambda: NOW)
    dump_cmd = next(args for args, step in docker.calls if step == "pg_dump")
    assert dump_cmd[:6] == ["docker", "compose", "exec", "-T", "db", "sh"]
    assert "-Fc -f /tmp/agila-20261024-183005.dump" in dump_cmd[-1]
    assert docker.steps() == [
        "count documents",
        "count chunks",
        "pg_dump",
        "copy",
        "clean-up",
        "count documents",
        "count chunks",
    ]
    assert all(">" not in command for command in docker.commands())  # no redirection (V90)


def test_backup_never_touches_env_or_prints_a_value(tmp_path, capsys):
    docker = FakeDocker()
    backup.main(docker, tmp_path, lambda: NOW)
    assert all(".env" not in command for command in docker.commands())
    assert "$POSTGRES" not in capsys.readouterr().out


def test_a_file_that_is_not_a_dump_is_refused_and_gets_no_counts_file(tmp_path, capsys):
    docker = FakeDocker(dump_bytes=b"\xff\xfeP\x00G\x00")  # what PowerShell `>` made (V90)
    assert backup.main(docker, tmp_path, lambda: NOW) == 1
    assert "is not a pg_dump file" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.counts.json"))


def test_a_library_that_changes_during_the_backup_is_refused(tmp_path, capsys):
    docker = FakeDocker(change_after=("pg_dump", REAL, {"documents": 5, "chunks": 53}))
    assert backup.main(docker, tmp_path, lambda: NOW) == 1
    assert "changed during the backup" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.counts.json"))


def test_a_failed_copy_is_one_sentence_and_still_cleans_the_container(tmp_path, capsys):
    docker = FakeDocker(fail="copy")
    assert backup.main(docker, tmp_path, lambda: NOW) == 1
    out = capsys.readouterr().out
    assert out.strip() == "Backup failed: The copy step failed (exit code 1)."
    assert "clean-up" in docker.steps()


def test_the_real_runner_hides_error_output(monkeypatch):
    class Result:
        returncode = 2
        stdout = ""
        stderr = 'FATAL: role "secret-user" does not exist'

    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(backup.CommandError) as err:
        backup.run(["docker", "compose", "exec"], "pg_dump")
    assert str(err.value) == "The pg_dump step failed (exit code 2)."


def test_a_missing_docker_is_one_sentence(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(backup.subprocess, "run", missing)
    with pytest.raises(backup.CommandError, match="Docker is not available"):
        backup.run(["docker", "compose", "ps"], "check")


# --- restore_test.py ---

import restore_test  # noqa: E402

TARGET = restore_test.TARGET


def _saved_dump(folder, name="agila-20261024-183005", counts=LIBRARY, data=b"PGDMP\x01fake"):
    dump = folder / f"{name}.dump"
    dump.write_bytes(data)
    (folder / f"{name}.counts.json").write_text(json.dumps(counts))
    return dump


def _restorable(restored=LIBRARY, **kwargs):
    return FakeDocker(counts={REAL: dict(LIBRARY), TARGET: dict(restored)}, **kwargs)


def test_a_matching_restore_passes_and_drops_the_test_database(tmp_path, capsys):
    _saved_dump(tmp_path)
    docker = _restorable()
    assert restore_test.main([], docker, tmp_path) == 0
    out = capsys.readouterr().out
    assert "documents 4 = 4" in out and "chunks 50 = 50" in out
    assert out.strip().endswith("Restore test passed.")
    assert docker.steps()[-1] == "dropdb"
    assert docker.calls[-1][0][-1] == f'dropdb -U "$POSTGRES_USER" {TARGET}'


@pytest.mark.parametrize("name", ["agila", "AGILA", "Agila", "postgres", "", "agila_test"])
def test_any_other_target_is_refused_before_any_command(tmp_path, capsys, name):
    _saved_dump(tmp_path)
    docker = _restorable()
    assert restore_test.main(["--target", name], docker, tmp_path) == 1
    assert "Restore test refused" in capsys.readouterr().out
    assert docker.calls == []


def test_a_real_database_with_the_test_name_is_refused_before_the_copy(tmp_path, capsys):
    _saved_dump(tmp_path)
    docker = _restorable(fail="target check")
    assert restore_test.main([], docker, tmp_path) == 1
    assert "Restore test refused" in capsys.readouterr().out
    assert docker.steps() == ["target check"]


def test_no_command_creates_or_drops_any_database_but_the_test_one(tmp_path):
    _saved_dump(tmp_path)
    docker = _restorable()
    restore_test.main([], docker, tmp_path)
    commands = docker.commands()
    assert not any(re.search(r"(^|\s)(-C|--create)(\s|$)", c) for c in commands)
    for args, step in docker.calls:
        if step in ("dropdb", "createdb", "pg_restore"):
            assert args[-1].split()[-1 if step != "pg_restore" else -2] == TARGET
            assert "POSTGRES_DB" not in args[-1]


def test_different_counts_fail_and_keep_the_test_database(tmp_path, capsys):
    _saved_dump(tmp_path)
    docker = _restorable(restored={"documents": 4, "chunks": 49})
    assert restore_test.main([], docker, tmp_path) == 1
    out = capsys.readouterr().out
    assert "chunks 50 != 49" in out
    assert f"The database {TARGET} was left in place" in out
    assert docker.steps().count("dropdb") == 1  # only the --if-exists before the restore


def test_a_failed_pg_restore_keeps_the_test_database_and_cleans_the_container(tmp_path, capsys):
    _saved_dump(tmp_path)
    docker = _restorable(fail="pg_restore")
    assert restore_test.main([], docker, tmp_path) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and TARGET in out
    assert docker.steps()[-1] == "clean-up"


def test_a_file_that_is_not_a_dump_is_refused_before_any_command(tmp_path, capsys):
    _saved_dump(tmp_path, data=b"\xff\xfeP\x00G\x00")
    docker = _restorable()
    assert restore_test.main([], docker, tmp_path) == 1
    assert "is not a pg_dump file" in capsys.readouterr().out
    assert docker.calls == []


def test_a_dump_without_its_counts_file_is_refused(tmp_path, capsys):
    _saved_dump(tmp_path)
    (tmp_path / "agila-20261024-183005.counts.json").unlink()
    docker = _restorable()
    assert restore_test.main([], docker, tmp_path) == 1
    assert "counts.json is missing" in capsys.readouterr().out
    assert docker.calls == []


def test_the_newest_dump_is_used_by_default(tmp_path, capsys):
    _saved_dump(tmp_path, "agila-20261023-090000", counts={"documents": 1, "chunks": 2})
    _saved_dump(tmp_path, "agila-20261024-183005")
    assert restore_test.main([], _restorable(), tmp_path) == 0
    assert "Restoring agila-20261024-183005.dump" in capsys.readouterr().out


def test_no_dump_at_all_is_one_sentence(tmp_path, capsys):
    assert restore_test.main([], _restorable(), tmp_path) == 1
    assert "No dump in" in capsys.readouterr().out
