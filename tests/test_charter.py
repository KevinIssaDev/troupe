"""Tests for `troupe charter` — structured, fully ungated charter edits
(design: decisions.md 2026-07-08, superseding the phase-1 propose/stage/
--approve gate). Same trust model as `troupe cast`: no TTY check, no
confirm prompt — a field edit is validated then applied immediately."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from troupe.cli import app
from troupe.scaffold import retire_members
from troupe.upgrade import upgrade

runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, ["charter", *args])


def state_of(project: Path) -> dict:
    return json.loads((project / ".troupe" / "casting-state.json").read_text(encoding="utf-8"))


def charter_of(project: Path, slug: str = "mason") -> Path:
    return project / ".troupe" / "agents" / slug / "charter.md"


def agent_def_of(project: Path, slug: str = "mason") -> Path:
    return project / ".claude" / "agents" / f"{slug}.md"


def snapshot(project: Path) -> dict[str, str]:
    return {
        "state": (project / ".troupe" / "casting-state.json").read_text(encoding="utf-8"),
        "charter": charter_of(project).read_text(encoding="utf-8"),
        "agent_def": agent_def_of(project).read_text(encoding="utf-8"),
        "team": (project / ".troupe" / "team.md").read_text(encoding="utf-8"),
        "decisions": (project / ".troupe" / "decisions.md").read_text(encoding="utf-8"),
    }


# ── apply ────────────────────────────────────────────────────────────


def test_apply_updates_all_four_surfaces(project: Path) -> None:
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


def test_apply_prints_what_changed(project: Path) -> None:
    result = invoke("mason", str(project), "--title", "Platform Core")
    assert result.exit_code == 0, result.output
    assert "Updated Mason's charter." in result.output
    assert ".claude/agents/mason.md" in result.output
    assert "team.md" in result.output


def test_title_only_change_rewrites_team_row_and_keeps_others(project: Path) -> None:
    result = invoke("mason", str(project), "--title", "Platform Core")
    assert result.exit_code == 0, result.output
    team = (project / ".troupe" / "team.md").read_text(encoding="utf-8")
    assert "| Mason | Platform Core |" in team
    assert "| Wright | Lead |" in team
    assert "| Sawyer | Tester |" in team


def test_use_hint_only_edit_skips_charter_md(project: Path) -> None:
    charter_before = charter_of(project).read_text(encoding="utf-8")

    result = invoke("mason", str(project), "--use-hint", "platform work")

    assert result.exit_code == 0, result.output
    assert charter_of(project).read_text(encoding="utf-8") == charter_before
    assert not charter_of(project).with_name("charter.md.bak").exists()
    record = state_of(project)["assignments"]["mason"]["charter"]
    assert record["use_hint"] == "platform work"
    assert record["title"] == "Backend"  # untouched fields keep the base values
    assert "Use for platform work." in agent_def_of(project).read_text(encoding="utf-8")


def test_no_op_edit_short_circuits(project: Path) -> None:
    before = snapshot(project)
    result = invoke("mason", str(project), "--title", "Backend")
    assert result.exit_code == 0, result.output
    assert "nothing to change" in result.output
    assert snapshot(project) == before


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
    result = invoke()
    assert result.exit_code == 2


def test_missing_ownership_anchor_aborts_with_zero_writes(project: Path) -> None:
    charter_path = charter_of(project)
    charter_path.write_text(
        charter_path.read_text(encoding="utf-8").replace("## Ownership", "## Stuff"),
        encoding="utf-8",
    )
    before = snapshot(project)

    result = invoke("mason", str(project), "--ownership", "Everything")

    assert result.exit_code == 1
    assert "## Ownership" in result.output
    assert snapshot(project) == before
    assert not (project / ".troupe" / "casting-state.json.bak").exists()
    assert not charter_path.with_name("charter.md.bak").exists()


def test_missing_charter_file_entirely_exits_1_with_zero_writes(project: Path) -> None:
    charter_of(project).unlink()
    before_state = state_of(project)

    result = invoke("mason", str(project), "--title", "Platform Core")

    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert state_of(project) == before_state


def test_crlf_charter_survives_anchor_rewrite(project: Path) -> None:
    """Windows scaffolds/hand edits may leave CRLF line endings. Python's
    text-mode read normalizes CRLF to \\n on read (and backup_and_write
    always writes \\n), so the anchor rewrite itself must still succeed —
    pinning that the whole file doesn't get silently dropped or mangled."""
    charter_path = charter_of(project)
    crlf_text = charter_path.read_text(encoding="utf-8").replace("\n", "\r\n")
    charter_path.write_bytes(crlf_text.encode("utf-8"))

    result = invoke("mason", str(project), "--title", "Platform Core")

    assert result.exit_code == 0, result.output
    text = charter_path.read_text(encoding="utf-8")
    assert "# Mason — Platform Core" in text
    assert "## Working agreements" in text


def test_missing_heading_anchor_aborts_title_change(project: Path) -> None:
    charter_path = charter_of(project)
    charter_path.write_text(
        charter_path.read_text(encoding="utf-8").replace("# Mason — Backend", "# Renamed"),
        encoding="utf-8",
    )
    before = snapshot(project)

    result = invoke("mason", str(project), "--title", "Platform Core")

    assert result.exit_code == 1
    assert snapshot(project) == before


# ── persistence contract with `troupe upgrade` ───────────────────────


def test_upgrade_after_charter_edit_leaves_agent_def_byte_identical(project: Path) -> None:
    """The 0.2.0 persistence contract: because the edit lands in
    casting-state's charter record, upgrade re-renders the exact same
    agent definition instead of reverting it."""
    result = invoke(
        "mason",
        str(project),
        "--title",
        "Platform Core",
        "--ownership",
        "CLI surface",
    )
    assert result.exit_code == 0, result.output
    agent_def = agent_def_of(project)
    before = agent_def.read_text(encoding="utf-8")

    upgrade_result = upgrade(project)

    assert agent_def.read_text(encoding="utf-8") == before
    assert agent_def in upgrade_result.unchanged
