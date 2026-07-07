"""Tests for `troupe cast --add-role`/`--retire` (docs: local design doc
cast-recast-retire.md) and the shared `governance/writes.py` primitive."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from troupe.casting.registry import allocate
from troupe.cli import app
from troupe.governance.writes import append_decision_entry, backup_and_write
from troupe.scaffold import (
    load_state,
    log_recast_decision,
    members_from_state,
    retire_members,
    scaffold,
)

runner = CliRunner()


def state_of(project: Path) -> dict:
    return json.loads((project / ".troupe" / "casting-state.json").read_text(encoding="utf-8"))


# ── governance/writes.py ────────────────────────────────────────────


def test_backup_and_write_creates_rotating_bak(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")

    backup_and_write(target, "updated-once")
    assert target.read_text(encoding="utf-8") == "updated-once"
    assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == "original"

    backup_and_write(target, "updated-twice")
    assert target.read_text(encoding="utf-8") == "updated-twice"
    # rotating, not accumulating: .bak holds the immediately-prior content only
    assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == "updated-once"


def test_backup_and_write_no_backup_when_file_absent(tmp_path: Path) -> None:
    target = tmp_path / "new.json"
    backup_and_write(target, "content")
    assert target.read_text(encoding="utf-8") == "content"
    assert not (tmp_path / "new.json.bak").exists()


def test_append_decision_entry_matches_documented_format(tmp_path: Path) -> None:
    troupe_dir = tmp_path / ".troupe"
    troupe_dir.mkdir()
    (troupe_dir / "decisions.md").write_text("# Decisions\n", encoding="utf-8")

    append_decision_entry(
        troupe_dir, date="2026-07-07", title="Did a thing", by="tester", what="X", why="Y"
    )

    text = (troupe_dir / "decisions.md").read_text(encoding="utf-8")
    assert text == (
        "# Decisions\n\n### 2026-07-07: Did a thing\n**By:** tester\n**What:** X\n**Why:** Y\n"
    )


# ── allocate() taken-names regression ────────────────────────────────


def test_taken_names_include_retired_slugs(project: Path) -> None:
    """The design's whole point: allocate()'s own docstring says a name is
    never reallocated, even for retired members. scaffold()/preview_cast()'s
    `taken` set previously came from active-only members, so this bug was
    dormant until retire existed. Retire Webster, then request a new
    frontend member: the freed role must get a brand-new name, never
    Webster."""
    retire_members(project, ["webster"])

    result = scaffold(project, roles=["frontend"])

    assert len(result.cast_added) == 1
    assert result.cast_added[0].name != "Webster"
    assert result.cast_added[0].role == "frontend"


def test_allocate_itself_is_unaware_of_retirement_status() -> None:
    # allocate() only ever sees the `taken` set its caller builds - this pins
    # that the fix lives in scaffold.py's set construction, not registry.py.
    cast = allocate(["frontend"], taken={"webster"})
    assert cast[0].name != "Webster"


# ── retire_members() ─────────────────────────────────────────────────


def test_retire_sets_status_and_pinned_timestamp_format(project: Path) -> None:
    result = retire_members(project, ["webster"])

    assert len(result.retired) == 1
    assert result.retired[0].name == "Webster"
    record = state_of(project)["assignments"]["webster"]
    assert record["status"] == "retired"
    # pinned format: datetime.now(UTC).isoformat(timespec="seconds") - an
    # explicit +00:00 offset, second precision, no microseconds.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", record["retiredAt"])
    # assignment fields besides status/retiredAt are preserved verbatim
    assert record["name"] == "Webster"
    assert record["role"] == "frontend"


def test_retire_deletes_compiled_agent_definition(project: Path) -> None:
    agent_def = project / ".claude" / "agents" / "webster.md"
    assert agent_def.exists()

    retire_members(project, ["webster"])

    assert not agent_def.exists()


def test_retire_never_touches_charter_or_history(project: Path) -> None:
    charter = project / ".troupe" / "agents" / "webster" / "charter.md"
    history = project / ".troupe" / "agents" / "webster" / "history.md"
    charter_before = charter.read_text(encoding="utf-8")
    history_before = history.read_text(encoding="utf-8")

    retire_members(project, ["webster"])

    assert charter.read_text(encoding="utf-8") == charter_before
    assert history.read_text(encoding="utf-8") == history_before


def test_retire_drops_row_from_team_md(project: Path) -> None:
    team_before = (project / ".troupe" / "team.md").read_text(encoding="utf-8")
    assert "Webster" in team_before

    retire_members(project, ["webster"])

    team_after = (project / ".troupe" / "team.md").read_text(encoding="utf-8")
    assert "Webster" not in team_after
    # everyone else's row survives
    for name in ("Wright", "Mason", "Sawyer"):
        assert name in team_after


def test_retire_backs_up_casting_state_before_mutating(project: Path) -> None:
    state_path = project / ".troupe" / "casting-state.json"
    original = state_path.read_text(encoding="utf-8")

    retire_members(project, ["webster"])

    backup = project / ".troupe" / "casting-state.json.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original
    assert state_path.read_text(encoding="utf-8") != original


def test_retire_is_case_insensitive(project: Path) -> None:
    result = retire_members(project, ["WEBSTER"])
    assert len(result.retired) == 1
    assert result.retired[0].name == "Webster"


def test_retire_unknown_name_reported_not_found(project: Path) -> None:
    result = retire_members(project, ["nobody"])
    assert result.not_found == ["nobody"]
    assert not result.retired


def test_retire_already_retired_name_reported(project: Path) -> None:
    retire_members(project, ["webster"])
    result = retire_members(project, ["webster"])
    assert result.already_retired == ["webster"]
    assert not result.retired


def test_retire_sole_member_of_role_warns_and_proceeds(project: Path) -> None:
    result = retire_members(project, ["webster"])
    assert len(result.retired) == 1
    assert any("frontend" in w for w in result.warnings)


def test_retire_non_sole_member_no_warning(project: Path) -> None:
    # cast a second backend so retiring the first isn't the last of its role.
    # A single "backend" request is a no-op (Mason already satisfies it, per
    # the multiset diff), so ask for two to force a genuinely new member.
    scaffold(project, roles=["backend", "backend"])
    result = retire_members(project, ["mason"])
    assert not result.warnings


def test_retire_multiple_names_in_one_call(project: Path) -> None:
    result = retire_members(project, ["webster", "sawyer"])
    assert {m.name for m in result.retired} == {"Webster", "Sawyer"}
    state = state_of(project)
    assert state["assignments"]["webster"]["status"] == "retired"
    assert state["assignments"]["sawyer"]["status"] == "retired"


def test_retire_no_op_when_nothing_retired_writes_no_backup(project: Path) -> None:
    backup = project / ".troupe" / "casting-state.json.bak"
    retire_members(project, ["nobody"])
    assert not backup.exists()


# ── --add-role reuse of scaffold() ───────────────────────────────────


def test_add_role_casts_only_the_new_role(project: Path) -> None:
    result = scaffold(project, roles=["security"])
    assert len(result.cast_added) == 1
    assert result.cast_added[0].role == "security"
    # nothing about the existing four members changed
    assert {m.role for m in result.cast_existing} == {"lead", "backend", "frontend", "tester"}


def test_add_role_already_covered_is_a_no_op(project: Path) -> None:
    result = scaffold(project, roles=["backend"])
    assert result.cast_added == []


def test_add_role_twice_adds_a_second_member(project: Path) -> None:
    result = scaffold(project, roles=["backend", "backend"])
    assert len(result.cast_added) == 1  # one already covers one request


# ── log_recast_decision() ────────────────────────────────────────────


def test_log_recast_decision_format_and_attribution(project: Path) -> None:
    retire_result = retire_members(project, ["webster"])
    add_result = scaffold(project, roles=["security"])

    log_recast_decision(
        project / ".troupe",
        retire_result.retired,
        add_result.cast_added,
        "swap frontend for security",
    )

    text = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert "Cast change via `troupe cast`" in text
    assert "**By:** troupe cast (CLI)" in text
    assert "Retired Webster (frontend)." in text
    assert "Cast" in text and "(Security)" in text
    assert "**Why:** swap frontend for security" in text


def test_log_recast_decision_no_reason_fallback(project: Path) -> None:
    retire_result = retire_members(project, ["webster"])
    log_recast_decision(project / ".troupe", retire_result.retired, [], None)

    text = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert "No reason given (--reason not passed)." in text


def test_log_recast_decision_no_op_when_nothing_changed(project: Path) -> None:
    before = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    log_recast_decision(project / ".troupe", [], [], "irrelevant")
    after = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert before == after


# ── CLI (`troupe cast`) ──────────────────────────────────────────────


def test_cli_no_flags_errors(project: Path) -> None:
    result = runner.invoke(app, ["cast", str(project)])
    assert result.exit_code == 2
    assert "Nothing to add or retire" in result.output


def test_cli_add_role(project: Path) -> None:
    result = runner.invoke(app, ["cast", str(project), "--add-role", "security"])
    assert result.exit_code == 0, result.output
    assert "Ward       Security" in result.output
    assert members_from_state(load_state(project / ".troupe"))
    assert any(m.role == "security" for m in members_from_state(load_state(project / ".troupe")))


def test_cli_retire(project: Path) -> None:
    result = runner.invoke(app, ["cast", str(project), "--retire", "webster"])
    assert result.exit_code == 0, result.output
    assert "Retired:" in result.output
    assert "Webster" in result.output
    active_roles = {m.role for m in members_from_state(load_state(project / ".troupe"))}
    assert "frontend" not in active_roles


def test_cli_retire_and_add_role_in_one_call(project: Path) -> None:
    result = runner.invoke(
        app,
        [
            "cast",
            str(project),
            "--retire",
            "webster",
            "--add-role",
            "security",
            "--reason",
            "swap frontend for security",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Retired:" in result.output
    assert "Cast:" in result.output
    decisions = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert decisions.count("Cast change via `troupe cast`") == 1  # one entry, not two


def test_cli_unknown_retire_name_exits_nonzero(project: Path) -> None:
    result = runner.invoke(app, ["cast", str(project), "--retire", "nobody"])
    assert result.exit_code == 1
    assert "no active cast member named 'nobody'" in result.output


def test_cli_already_retired_name_exits_nonzero(project: Path) -> None:
    runner.invoke(app, ["cast", str(project), "--retire", "webster"])
    result = runner.invoke(app, ["cast", str(project), "--retire", "webster"])
    assert result.exit_code == 1
    assert "already retired" in result.output


def test_cli_sole_member_retirement_prints_warning(project: Path) -> None:
    result = runner.invoke(app, ["cast", str(project), "--retire", "webster"])
    assert result.exit_code == 0
    assert "Warning: no active frontend remains after this change." in result.output


# ── scaffold/upgrade parity for the new troupe-cast.md file ─────────


def test_scaffolded_troupe_cast_command_matches_upgrade_template(project: Path) -> None:
    from troupe.upgrade import upgrade

    command = project / ".claude" / "commands" / "troupe-cast.md"
    assert command.is_file()
    before = command.read_text(encoding="utf-8")

    result = upgrade(project)

    assert command not in result.refreshed
    assert command in result.unchanged
    assert command.read_text(encoding="utf-8") == before


def test_upgrade_restores_stale_troupe_cast_command(project: Path) -> None:
    from troupe.upgrade import upgrade

    command = project / ".claude" / "commands" / "troupe-cast.md"
    original = command.read_text(encoding="utf-8")
    command.write_text("# tampered\n", encoding="utf-8")

    result = upgrade(project)

    assert command.read_text(encoding="utf-8") == original
    assert command in result.refreshed
