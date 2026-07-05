"""End-to-end tests for `troupe init`: run against a temp dir, assert the tree."""

import json
from pathlib import Path

from typer.testing import CliRunner

from troupe.cli import app

runner = CliRunner()


def run_init(path: Path, *args: str) -> str:
    result = runner.invoke(app, ["init", str(path), *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_init_creates_expected_tree(tmp_path: Path) -> None:
    run_init(tmp_path)

    for rel in (
        ".troupe/team.md",
        ".troupe/decisions.md",
        ".troupe/directives.md",
        ".troupe/config.json",
        ".troupe/casting-state.json",
        ".troupe/agents/wright/charter.md",
        ".troupe/agents/wright/history.md",
        ".troupe/agents/mason/charter.md",
        ".troupe/agents/webster/charter.md",
        ".troupe/agents/sawyer/charter.md",
        ".claude/agents/wright.md",
        ".claude/agents/mason.md",
        ".claude/agents/webster.md",
        ".claude/agents/sawyer.md",
    ):
        assert (tmp_path / rel).is_file(), f"missing {rel}"


def test_agent_definition_has_valid_frontmatter(tmp_path: Path) -> None:
    run_init(tmp_path)
    text = (tmp_path / ".claude/agents/wright.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: wright" in text
    assert "description: Wright" in text
    assert "You are **Wright**" in text


def test_team_md_lists_full_cast(tmp_path: Path) -> None:
    run_init(tmp_path)
    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    for name in ("Wright", "Mason", "Webster", "Sawyer"):
        assert name in team


def test_reinit_preserves_state(tmp_path: Path) -> None:
    run_init(tmp_path)

    decisions = tmp_path / ".troupe/decisions.md"
    history = tmp_path / ".troupe/agents/wright/history.md"
    decisions.write_text("# Decisions\n\n### 2026-07-06: Chose sqlite\n", encoding="utf-8")
    history.write_text("# Wright — History\n\nLearned things.\n", encoding="utf-8")

    run_init(tmp_path)

    assert "Chose sqlite" in decisions.read_text(encoding="utf-8")
    assert "Learned things." in history.read_text(encoding="utf-8")


def test_reinit_with_new_role_extends_cast(tmp_path: Path) -> None:
    run_init(tmp_path)
    run_init(tmp_path, "--roles", "lead,backend,frontend,tester,security")

    assert (tmp_path / ".troupe/agents/ward/charter.md").is_file()
    assert (tmp_path / ".claude/agents/ward.md").is_file()

    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert set(state["assignments"]) == {"wright", "mason", "webster", "sawyer", "ward"}

    # team.md roster table was regenerated to include Ward, around user content
    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    assert "Ward" in team


def test_reinit_same_roles_casts_nothing_new(tmp_path: Path) -> None:
    run_init(tmp_path)
    before = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    output = run_init(tmp_path)
    after = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert before == after
    assert "Already on the roster" in output
