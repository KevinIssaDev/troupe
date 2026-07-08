"""End-to-end tests for `troupe init`: run against a temp dir, assert the tree.

`troupe init` casts nobody — it unconditionally scaffolds governance
(hooks, settings, empty casting-state.json, empty team.md Cast table, all
three command templates) and points the user at /troupe-setup to cast a
real team. No scan, no flags, no confirmation prompt.
"""

import json
from pathlib import Path

from typer.testing import CliRunner

from troupe.cli import app

runner = CliRunner()


def run_init(path: Path) -> str:
    result = runner.invoke(app, ["init", str(path)])
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
        ".troupe/policy.json",
        ".claude/settings.json",
        ".claude/commands/troupe-explore.md",
        ".claude/commands/troupe-cast.md",
        ".claude/commands/troupe-setup.md",
    ):
        assert (tmp_path / rel).is_file(), f"missing {rel}"


def test_init_casts_nobody(tmp_path: Path) -> None:
    run_init(tmp_path)

    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert state["assignments"] == {}

    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    assert "| Name | Role | Charter | Status |" in team
    # No rows in the cast table - just header/separator, then the next section.
    cast_section = team[team.find("## Cast") : team.find("## How this works")]
    assert cast_section.count("\n|") == 2  # header + separator only

    assert not (tmp_path / ".troupe/agents").exists()
    assert not (tmp_path / ".claude/agents").exists()


def test_hooks_and_settings_wired_with_zero_cast(tmp_path: Path) -> None:
    run_init(tmp_path)

    settings = json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))
    blob = json.dumps(settings.get("hooks", {}))
    assert "troupe_file_guard.py" in blob
    assert "troupe_session_context.py" in blob


def test_init_guidance_points_to_troupe_setup(tmp_path: Path) -> None:
    output = run_init(tmp_path)
    assert "Next: commit .troupe/ and .claude/ so the team travels with the repo." in output
    assert (
        "No cast yet — that's expected. Open Claude Code and run /troupe-setup to cast "
        "your team, grounded in a real read of this repo." in output
    )


def test_init_exits_0(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0


def test_troupe_setup_command_has_load_bearing_phrases(tmp_path: Path) -> None:
    """Content-pin test: the scaffolded /troupe-setup template must retain
    the load-bearing conventions from its design (decisions.md 2026-07-08),
    not just exist."""
    run_init(tmp_path)
    text = (tmp_path / ".claude/commands/troupe-setup.md").read_text(encoding="utf-8")

    assert "25 file reads" in text or "~25" in text  # bounded-read ceiling
    assert "troupe cast --add-role" in text
    assert "troupe charter" in text
    assert "ask first" in text.lower() or "say so plainly and ask first" in text
    assert "apply directly" in text
    assert "history.md" in text and "never here" in text  # exploit/tribal-knowledge rule


def test_reinit_after_cast_reports_existing_cast_not_no_cast_yet(tmp_path: Path) -> None:
    """Regression: bare `init` re-run after a member has been cast (e.g. via
    `troupe cast --add-role`) must not repeat the "No cast yet" guidance —
    that message is only true on a genuinely cast-less repo."""
    run_init(tmp_path)

    add_result = runner.invoke(app, ["cast", str(tmp_path), "--add-role", "tester"])
    assert add_result.exit_code == 0, add_result.output

    output = run_init(tmp_path)
    assert "No cast yet" not in output
    assert "Cast already assembled" in output

    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert state["assignments"]  # the earlier cast survived the re-init untouched


def test_reinit_after_cast_leaves_casting_state_untouched(tmp_path: Path) -> None:
    """Pins the widened scaffold() write condition
    (`new_members or not <state file>.exists()`, decisions.md 2026-07-08):
    a bare re-init must never rewrite an existing cast back to empty. Asserts
    full before/after equality of the assignments dict, not just truthiness."""
    run_init(tmp_path)

    add_result = runner.invoke(app, ["cast", str(tmp_path), "--add-role", "tester"])
    assert add_result.exit_code == 0, add_result.output

    before = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert before["assignments"]  # sanity: the member really is cast

    run_init(tmp_path)

    after = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert after["assignments"] == before["assignments"]


def test_reinit_is_idempotent(tmp_path: Path) -> None:
    run_init(tmp_path)

    decisions = tmp_path / ".troupe/decisions.md"
    decisions.write_text("# Decisions\n\n### 2026-07-06: Chose sqlite\n", encoding="utf-8")

    before = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    output = run_init(tmp_path)
    after = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))

    assert before == after
    assert "Chose sqlite" in decisions.read_text(encoding="utf-8")
    assert "Created 0 file(s)" in output
