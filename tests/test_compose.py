"""The n8n service in compose.yaml (block r, research 2t, plan "Block r, s, t plan").

The file is read as text, so no YAML package is needed. Comments after ` #` are ignored.
"""

from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
COMPOSE = PROJECT / "compose.yaml"
GITIGNORE = PROJECT / ".gitignore"
N8N_IMAGE = (
    "n8nio/n8n:2.45.5@sha256:9f6d0a5987ab5a297c4b0b38fbf1a22285dd1364551478e93f03d506908fa74c"
)


def _code(line: str) -> str:
    return line.split(" #")[0].rstrip()


def _lines() -> list[str]:
    return [_code(line) for line in COMPOSE.read_text(encoding="utf-8").splitlines()]


def _service(name: str) -> list[str]:
    """The lines of one service: from `  <name>:` to the next service or top-level key."""
    lines = _lines()
    try:
        start = lines.index(f"  {name}:")
    except ValueError:
        pytest.fail(f"compose.yaml has no service {name}")
    block = []
    for line in lines[start + 1 :]:
        if line and (not line.startswith(" ") or (line[:2] == "  " and line[2] != " ")):
            break
        block.append(line)
    return block


def _ports(name: str) -> list[str]:
    block = _service(name)
    start = block.index("    ports:")
    ports = []
    for line in block[start + 1 :]:
        if not line.startswith("      "):
            break
        ports.append(line.strip())
    return ports


def _top_level_volumes() -> list[str]:
    lines = _lines()
    start = lines.index("volumes:")
    volumes = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        volumes.append(line)
    return volumes


def test_n8n_image_is_2_45_5_pinned_by_digest():
    assert f"    image: {N8N_IMAGE}" in _service("n8n")


def test_n8n_is_published_only_on_127_0_0_1_5678():
    assert _ports("n8n") == ['- "127.0.0.1:5678:5678"']


def test_n8n_starts_only_with_its_profile():
    assert '    profiles: ["n8n"]' in _service("n8n")


def test_n8n_clock_and_schedules_use_asia_manila():
    block = _service("n8n")
    assert "      TZ: Asia/Manila" in block
    assert "      GENERIC_TIMEZONE: Asia/Manila" in block


def test_n8n_telemetry_is_off():
    assert '      N8N_DIAGNOSTICS_ENABLED: "false"' in _service("n8n")


def test_n8n_takes_nothing_from_env():
    text = "\n".join(_service("n8n"))
    assert "${" not in text
    for prefix in ("AGILA_", "POSTGRES_", "DISCORD_"):
        assert prefix not in text


def test_n8n_keeps_the_default_scheduler():
    """2.45.5's defaults run missed executions (V158); turning either off would stop that."""
    text = "\n".join(_service("n8n"))
    assert "N8N_SCHEDULER_ENABLED" not in text
    assert "N8N_USE_WORKFLOW_PUBLICATION_SERVICE" not in text


def test_n8n_data_has_its_own_volume():
    assert "      - n8n_data:/home/node/.n8n" in _service("n8n")
    assert "  n8n_data:" in _top_level_volumes()


def test_n8n_waits_for_a_healthy_api():
    text = "\n".join(_service("n8n"))
    assert "    depends_on:\n      api:\n        condition: service_healthy" in text


def test_n8n_never_restarts_by_itself():
    assert '    restart: "no"' in _service("n8n")


def test_api_and_db_are_still_published_only_on_127_0_0_1():
    assert _ports("api") == ['- "127.0.0.1:8000:8000"']
    assert _ports("db") == ['- "127.0.0.1:5433:5432"']


def test_n8n_exports_are_ignored_by_git():
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
    assert "n8n/" in [line.strip() for line in lines]
