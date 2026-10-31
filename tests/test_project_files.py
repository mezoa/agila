"""The release files of block v: LICENSE, the GitHub Action and the README (plan "Block t, u, v
plan", research 2u). Read as text only; nothing here runs the Action or a command."""

from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
LICENSE = PROJECT / "LICENSE"
CI = PROJECT / ".github" / "workflows" / "ci.yml"
README = PROJECT / "README.md"
CHECKOUT = "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"  # v7.0.1 (V168)
SETUP_UV = "uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884"  # v10.3.0 (V169)


def _text(path: Path) -> str:
    assert path.exists(), f"{path.relative_to(PROJECT)} is missing"
    return path.read_text(encoding="utf-8")


def _code_lines(path: Path) -> list[str]:
    """The lines without their ` #` comments and outer spaces."""
    return [line.split(" #")[0].strip() for line in _text(path).splitlines()]


def test_license_is_mit():
    lines = _text(LICENSE).splitlines()
    assert lines[0] == "MIT License"
    assert any(line.startswith("Copyright (c) 2026 ") for line in lines)


def test_ci_runs_ruff_and_the_plain_tests_on_windows():
    lines = _code_lines(CI)
    for expected in (
        "runs-on: windows-latest",
        f"- {CHECKOUT}",
        f"- {SETUP_UV}",
        'version: "0.12.17"',
        "- run: uv sync --locked",
        "- run: uv run ruff check .",
        "- run: uv run pytest",
    ):
        assert expected in lines, expected


def test_ci_needs_no_secret_and_no_database():
    text = _text(CI)
    lines = _code_lines(CI)
    assert "secrets." not in text
    assert "-m db" not in text and "-m live" not in text
    assert "permissions:" in lines and "contents: read" in lines


def test_readme_lists_the_host_prerequisites_before_the_quick_start():
    text = _text(README)
    assert "## Host prerequisites" in text and "## Quick start" in text
    before = text[text.index("## Host prerequisites") : text.index("## Quick start")]
    for name in ("Docker Desktop", "Ollama", "qwen3.5:4b", "uv"):
        assert name in before, name
