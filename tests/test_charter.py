"""Tests for `troupe charter` — structured charter edits with a
proposal/approve human gate (design: decisions.md 2026-07-07).

TTY-vs-non-TTY: CliRunner's stdin is not a TTY, so the staging path is the
default; TTY flows fake `sys.stdin.isatty()` on the command module exactly
like test_init.py's `fake_tty` and read the confirm answer from CliRunner's
injected input.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import troupe.commands.charter as charter_command
from troupe.cli import app
from troupe.scaffold import retire_members
from troupe.upgrade import upgrade

runner = CliRunner()


def fake_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        charter_command,
        "sys",
        types.SimpleNamespace(stdin=types.SimpleNamespace(isatty=lambda: True)),
    )


def invoke(*args: str, input: str | None = None):
    return runner.invoke(app, ["charter", *args], input=input)


def state_of(project: Path) -> dict:
    return json.loads((project / ".troupe" / "casting-state.json").read_text(encoding="utf-8"))


def charter_of(project: Path, slug: str = "mason") -> Path:
    return project / ".troupe" / "agents" / slug / "charter.md"


def agent_def_of(project: Path, slug: str = "mason") -> Path:
    return project / ".claude" / "agents" / f"{slug}.md"


def proposal_of(project: Path, slug: str = "mason") -> Path:
    return project / ".troupe" / "proposals" / f"charter-{slug}.json"


def snapshot(project: Path) -> dict[str, str]:
    return {
        "state": (project / ".troupe" / "casting-state.json").read_text(encoding="utf-8"),
        "charter": charter_of(project).read_text(encoding="utf-8"),
        "agent_def": agent_def_of(project).read_text(encoding="utf-8"),
        "team": (project / ".troupe" / "team.md").read_text(encoding="utf-8"),
        "decisions": (project / ".troupe" / "decisions.md").read_text(encoding="utf-8"),
    }


# ── TTY apply ────────────────────────────────────────────────────────


def test_tty_apply_updates_all_four_surfaces(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    # Hand-written prose outside the anchors must survive the surgical rewrite.
    charter_path = charter_of(project)
    charter_path.write_text(
        charter_path.read_text(encoding="utf-8") + "\n## Notes\n\nHand-written note kept.\n",
        encoding="utf-8",
    )

    result = invoke(
        "mason",
        str(project),
        "--title",
        "Platform Core",
        "--expertise",
        "Core CLI and data models",
        "--ownership",
        "CLI surface",
        "--ownership",
        "Data models",
        "--use-hint",
        "core work",
        "--reason",
        "specialize mason",
        input="y\n",
    )
    assert result.exit_code == 0, result.output

    # 1. casting-state's charter record — the system of record.
    record = state_of(project)["assignments"]["mason"]["charter"]
    assert record == {
        "title": "Platform Core",
        "expertise": "Core CLI and data models",
        "ownership": ["CLI surface", "Data models"],
        "use_hint": "core work",
    }

    # 2. charter.md: changed anchors rewritten, everything else preserved.
    text = charter_path.read_text(encoding="utf-8")
    assert "# Mason — Platform Core" in text
    assert "- **Role:** Platform Core" in text
    assert "- **Expertise:** Core CLI and data models" in text
    assert "- CLI surface\n- Data models" in text
    assert "Server-side code" not in text  # the old ownership list is replaced
    assert "## Working agreements" in text
    assert "Hand-written note kept." in text

    # 3. the recompiled agent definition carries the new mandate.
    agent_text = agent_def_of(project).read_text(encoding="utf-8")
    assert "Platform Core" in agent_text
    assert "Use for core work." in agent_text
    assert "- CLI surface" in agent_text

    # 4. team.md roster row and the decision entry.
    team = (project / ".troupe" / "team.md").read_text(encoding="utf-8")
    assert "| Mason | Platform Core |" in team
    decisions = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert "Charter change for Mason via `troupe charter`" in decisions
    assert "**By:** troupe charter (CLI)" in decisions
    assert "**Why:** specialize mason" in decisions

    # backup_and_write leaves rotating .bak files behind.
    assert (project / ".troupe" / "casting-state.json.bak").exists()
    assert charter_path.with_name("charter.md.bak").exists()


def test_tty_apply_shows_diff_and_recompile_note(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    result = invoke("mason", str(project), "--title", "Platform Core", input="y\n")
    assert result.exit_code == 0, result.output
    assert "-# Mason — Backend" in result.output
    assert "+# Mason — Platform Core" in result.output
    assert ".claude/agents/mason.md" in result.output
    assert "team.md" in result.output


def test_tty_declined_confirm_writes_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    before = snapshot(project)

    result = invoke("mason", str(project), "--title", "Platform Core", input="n\n")

    assert result.exit_code == 0, result.output
    assert "Nothing written." in result.output
    assert snapshot(project) == before
    assert not (project / ".troupe" / "casting-state.json.bak").exists()
    assert not proposal_of(project).exists()


def test_title_only_change_rewrites_team_row_and_keeps_others(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    result = invoke("mason", str(project), "--title", "Platform Core", input="y\n")
    assert result.exit_code == 0, result.output
    team = (project / ".troupe" / "team.md").read_text(encoding="utf-8")
    assert "| Mason | Platform Core |" in team
    assert "| Wright | Lead |" in team
    assert "| Sawyer | Tester |" in team


def test_use_hint_only_edit_skips_charter_md(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    charter_before = charter_of(project).read_text(encoding="utf-8")

    result = invoke("mason", str(project), "--use-hint", "platform work", input="y\n")

    assert result.exit_code == 0, result.output
    assert "use hint is not rendered" in result.output
    assert charter_of(project).read_text(encoding="utf-8") == charter_before
    assert not charter_of(project).with_name("charter.md.bak").exists()
    record = state_of(project)["assignments"]["mason"]["charter"]
    assert record["use_hint"] == "platform work"
    assert record["title"] == "Backend"  # untouched fields keep the base values
    assert "Use for platform work." in agent_def_of(project).read_text(encoding="utf-8")


def test_no_op_edit_short_circuits_without_prompting(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    before = snapshot(project)
    # No confirm input is supplied: if the command reached the prompt it
    # would abort, so exit 0 proves the no-op short-circuit fired first.
    result = invoke("mason", str(project), "--title", "Backend")
    assert result.exit_code == 0, result.output
    assert "nothing to change" in result.output
    assert snapshot(project) == before


# ── proposal staging (non-TTY / --propose) ───────────────────────────


def test_non_tty_field_edit_stages_proposal_only(project: Path) -> None:
    before = snapshot(project)

    result = invoke("mason", str(project), "--title", "Platform Core", "--reason", "why not")

    assert result.exit_code == 0, result.output
    assert snapshot(project) == before  # nothing applied
    proposal = json.loads(proposal_of(project).read_text(encoding="utf-8"))
    assert proposal["slug"] == "mason"
    assert proposal["fields"] == {"title": "Platform Core"}
    assert proposal["reason"] == "why not"
    assert proposal["stagedAt"]
    assert "troupe charter mason" in result.output
    assert "--approve" in result.output


def test_propose_flag_forces_staging_even_on_tty(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    before = snapshot(project)
    result = invoke("mason", str(project), "--title", "Platform Core", "--propose")
    assert result.exit_code == 0, result.output
    assert proposal_of(project).exists()
    assert snapshot(project) == before


def test_restaging_overwrites_pending_proposal_with_notice(project: Path) -> None:
    invoke("mason", str(project), "--title", "First Title")
    result = invoke("mason", str(project), "--title", "Second Title")

    assert result.exit_code == 0, result.output
    assert "Replaced" in result.output
    proposal = json.loads(proposal_of(project).read_text(encoding="utf-8"))
    assert proposal["fields"] == {"title": "Second Title"}


# ── --approve / --reject / --list ────────────────────────────────────


def test_approve_non_tty_exits_2_and_keeps_proposal(project: Path) -> None:
    invoke("mason", str(project), "--title", "Platform Core")
    before = snapshot(project)

    result = invoke("mason", str(project), "--approve")

    assert result.exit_code == 2
    assert "human" in result.output
    assert proposal_of(project).exists()
    assert snapshot(project) == before


def test_approve_applies_deletes_proposal_and_logs(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoke("mason", str(project), "--title", "Platform Core", "--reason", "staged reason")
    fake_tty(monkeypatch)

    result = invoke("mason", str(project), "--approve", input="y\n")

    assert result.exit_code == 0, result.output
    assert not proposal_of(project).exists()
    assert state_of(project)["assignments"]["mason"]["charter"]["title"] == "Platform Core"
    assert "# Mason — Platform Core" in charter_of(project).read_text(encoding="utf-8")
    decisions = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert "staged proposal (propose-then-approve)" in decisions
    assert "**Why:** staged reason" in decisions


def test_approve_renders_diff_from_proposal_file(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stage-then-tamper closure: whatever the proposal file says at
    approve time is what the human sees and what gets applied."""
    invoke("mason", str(project), "--title", "Innocent Title")
    proposal_path = proposal_of(project)
    tampered = json.loads(proposal_path.read_text(encoding="utf-8"))
    tampered["fields"]["title"] = "Tampered Title"
    proposal_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    fake_tty(monkeypatch)

    result = invoke("mason", str(project), "--approve", input="n\n")

    assert result.exit_code == 0, result.output
    assert "Tampered Title" in result.output  # the human reviews the tampered value
    assert "Innocent Title" not in result.output


def test_approve_declined_keeps_proposal(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invoke("mason", str(project), "--title", "Platform Core")
    fake_tty(monkeypatch)
    before = snapshot(project)

    result = invoke("mason", str(project), "--approve", input="n\n")

    assert result.exit_code == 0, result.output
    assert proposal_of(project).exists()
    assert snapshot(project) == before


def test_approve_with_nothing_pending_exits_1(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    result = invoke("mason", str(project), "--approve")
    assert result.exit_code == 1
    assert "no pending charter proposal" in result.output


def test_reject_discards_proposal(project: Path) -> None:
    invoke("mason", str(project), "--title", "Platform Core")
    result = invoke("mason", str(project), "--reject")
    assert result.exit_code == 0, result.output
    assert not proposal_of(project).exists()


def test_reject_with_nothing_pending_exits_1(project: Path) -> None:
    result = invoke("mason", str(project), "--reject")
    assert result.exit_code == 1


def test_list_shows_pending_proposals(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invoke("mason", str(project), "--title", "Platform Core")
    invoke("sawyer", str(project), "--use-hint", "breaking things")

    result = invoke("mason", str(project), "--list")
    assert result.exit_code == 0, result.output
    assert "mason" in result.output
    assert "sawyer" not in result.output
    assert "--approve" in result.output

    monkeypatch.chdir(project)  # NAME-less --list runs against the cwd
    result = invoke("--list")
    assert result.exit_code == 0, result.output
    assert "mason" in result.output
    assert "sawyer" in result.output


def test_list_with_nothing_pending_says_so(project: Path) -> None:
    result = invoke("mason", str(project), "--list")
    assert result.exit_code == 0, result.output
    assert "No pending charter proposals." in result.output


# ── errors and usage ─────────────────────────────────────────────────


def test_unknown_member_exits_1(project: Path) -> None:
    result = invoke("nobody", str(project), "--title", "X")
    assert result.exit_code == 1
    assert "no cast member named 'nobody'" in result.output


def test_retired_member_exits_1(project: Path) -> None:
    retire_members(project, ["webster"])
    result = invoke("webster", str(project), "--title", "X")
    assert result.exit_code == 1
    assert "retired" in result.output


def test_no_field_flags_exits_2(project: Path) -> None:
    result = invoke("mason", str(project))
    assert result.exit_code == 2
    assert "Nothing to change" in result.output


def test_missing_name_exits_2(project: Path) -> None:
    result = invoke("--title", "X")
    assert result.exit_code == 2
    assert "Missing cast member name" in result.output


def test_approve_cannot_combine_with_field_flags(project: Path) -> None:
    result = invoke("mason", str(project), "--approve", "--title", "X")
    assert result.exit_code == 2


def test_approve_and_reject_are_mutually_exclusive(project: Path) -> None:
    result = invoke("mason", str(project), "--approve", "--reject")
    assert result.exit_code == 2


def test_missing_ownership_anchor_aborts_with_zero_writes(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    charter_path = charter_of(project)
    charter_path.write_text(
        charter_path.read_text(encoding="utf-8").replace("## Ownership", "## Stuff"),
        encoding="utf-8",
    )
    before = snapshot(project)

    result = invoke("mason", str(project), "--ownership", "Everything", input="y\n")

    assert result.exit_code == 1
    assert "## Ownership" in result.output
    assert snapshot(project) == before
    assert not (project / ".troupe" / "casting-state.json.bak").exists()
    assert not charter_path.with_name("charter.md.bak").exists()


def test_missing_heading_anchor_aborts_title_change(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    charter_path = charter_of(project)
    charter_path.write_text(
        charter_path.read_text(encoding="utf-8").replace("# Mason — Backend", "# Renamed"),
        encoding="utf-8",
    )
    before = snapshot(project)

    result = invoke("mason", str(project), "--title", "Platform Core", input="y\n")

    assert result.exit_code == 1
    assert snapshot(project) == before


# ── persistence contract with `troupe upgrade` ───────────────────────


def test_upgrade_after_charter_edit_leaves_agent_def_byte_identical(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 0.2.0 persistence contract: because the edit lands in
    casting-state's charter record, upgrade re-renders the exact same
    agent definition instead of reverting it."""
    fake_tty(monkeypatch)
    result = invoke(
        "mason",
        str(project),
        "--title",
        "Platform Core",
        "--ownership",
        "CLI surface",
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    agent_def = agent_def_of(project)
    before = agent_def.read_text(encoding="utf-8")

    upgrade_result = upgrade(project)

    assert agent_def.read_text(encoding="utf-8") == before
    assert agent_def in upgrade_result.unchanged
