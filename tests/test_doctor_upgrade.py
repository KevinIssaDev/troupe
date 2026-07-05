"""Tests for `troupe doctor` and `troupe upgrade`."""

import json
from pathlib import Path

from typer.testing import CliRunner

from troupe.cli import app
from troupe.commands.doctor import run_checks
from troupe.upgrade import upgrade

runner = CliRunner()


def statuses(root: Path) -> dict[str, str]:
    return {c.name: c.status for c in run_checks(root)}


# ── doctor ───────────────────────────────────────────────────────────


def test_doctor_healthy_project_exits_zero(project: Path) -> None:
    result = runner.invoke(app, ["doctor", str(project)])
    assert result.exit_code == 0, result.output
    assert "0 failure(s)" in result.output


def test_doctor_fails_outside_troupe_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 1
    assert "troupe init" in result.output


def test_doctor_fails_on_missing_hook_script(project: Path) -> None:
    (project / ".claude" / "hooks" / "troupe_file_guard.py").unlink()
    assert statuses(project)["hook scripts"] == "fail"


def test_doctor_warns_on_stale_hook_script(project: Path) -> None:
    script = project / ".claude" / "hooks" / "troupe_file_guard.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# old\n", encoding="utf-8")
    assert statuses(project)["hook scripts"] == "warn"


def test_doctor_fails_on_unwired_settings(project: Path) -> None:
    settings_path = project / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    del settings["hooks"]["TeammateIdle"]
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    assert statuses(project)["settings wiring"] == "fail"


def test_doctor_warns_on_missing_policy_knob(project: Path) -> None:
    policy_path = project / ".troupe" / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    del policy["idleNudge"]
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    assert statuses(project)["policy"] == "warn"


def test_doctor_fails_on_missing_cast_files(project: Path) -> None:
    (project / ".claude" / "agents" / "wright.md").unlink()
    assert statuses(project)["cast files"] == "fail"


# ── upgrade ──────────────────────────────────────────────────────────


def test_upgrade_restores_stale_hooks_and_agent_defs(project: Path) -> None:
    hook = project / ".claude" / "hooks" / "troupe_file_guard.py"
    agent_def = project / ".claude" / "agents" / "wright.md"
    hook_original = hook.read_text(encoding="utf-8")
    def_original = agent_def.read_text(encoding="utf-8")
    hook.write_text("# tampered\n", encoding="utf-8")
    agent_def.write_text("# tampered\n", encoding="utf-8")

    result = upgrade(project)

    assert hook.read_text(encoding="utf-8") == hook_original
    assert agent_def.read_text(encoding="utf-8") == def_original
    assert hook in result.refreshed
    assert agent_def in result.refreshed


def test_upgrade_adds_missing_policy_knobs_preserving_user_edits(project: Path) -> None:
    policy_path = project / ".troupe" / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    del policy["piiScrub"]  # simulate a pre-M3 project
    policy["reviewGate"] = {"enabled": True, "taskPatterns": ["*deploy*"]}  # user edit
    policy["protectedPaths"] = [".env"]  # user trimmed the defaults
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    upgrade(project)

    upgraded = json.loads(policy_path.read_text(encoding="utf-8"))
    assert upgraded["piiScrub"]["enabled"] is True  # restored from defaults
    assert upgraded["reviewGate"] == {"enabled": True, "taskPatterns": ["*deploy*"]}
    assert upgraded["protectedPaths"] == [".env"]  # user's trim respected


def test_upgrade_rewires_deleted_settings_entries(project: Path) -> None:
    settings_path = project / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    del settings["hooks"]["SessionStart"]
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    upgrade(project)

    rewired = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "troupe_session_context.py" in json.dumps(rewired["hooks"]["SessionStart"])


def test_upgrade_never_touches_team_state(project: Path) -> None:
    decisions = project / ".troupe" / "decisions.md"
    charter = project / ".troupe" / "agents" / "wright" / "charter.md"
    decisions.write_text("# Decisions\n\n### 2026-07-06: Ours\n", encoding="utf-8")
    charter.write_text("# Wright — customized\n", encoding="utf-8")

    upgrade(project)

    assert decisions.read_text(encoding="utf-8") == "# Decisions\n\n### 2026-07-06: Ours\n"
    assert charter.read_text(encoding="utf-8") == "# Wright — customized\n"


def test_upgrade_is_idempotent(project: Path) -> None:
    first = upgrade(project)
    second = upgrade(project)
    assert not second.refreshed
    assert not second.extended
    assert len(second.unchanged) >= len(first.refreshed)


def test_upgrade_errors_outside_troupe_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["upgrade", str(tmp_path)])
    assert result.exit_code == 1


def test_doctor_clean_after_upgrade_of_degraded_project(project: Path) -> None:
    # degrade: stale hook + missing policy knob + unwired event
    hook = project / ".claude" / "hooks" / "troupe_idle_nudge.py"
    hook.write_text("# old\n", encoding="utf-8")
    policy_path = project / ".troupe" / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    del policy["reviewGate"]
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    upgrade(project)

    assert all(c.status in ("ok", "info") for c in run_checks(project)), run_checks(project)
