"""Tests for the M3 governance hooks: PII scrub, review gate, idle nudge,
session context."""

import json
from pathlib import Path

from conftest import run_hook, update_policy, write_payload

# ── PII scrub ────────────────────────────────────────────────────────


def test_pii_scrub_redacts_emails_via_updated_input(project: Path) -> None:
    payload = write_payload(
        project,
        "docs/contact.md",
        content="Reach kevin.real@corp.io or support@example.com for help.",
    )
    proc = run_hook(project, "troupe_pii_scrub.py", payload)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    updated = out["hookSpecificOutput"]["updatedInput"]["content"]
    assert "kevin.real@corp.io" not in updated
    assert "[email-redacted]" in updated
    assert "support@example.com" in updated  # allowlisted
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "redacted 1 email" in out["systemMessage"]


def test_pii_scrub_silent_when_clean(project: Path) -> None:
    proc = run_hook(project, "troupe_pii_scrub.py", write_payload(project, "src/a.py"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_pii_scrub_covers_edit_new_string(project: Path) -> None:
    payload = {
        "hook_event_name": "PreToolUse",
        "cwd": str(project),
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(project / "src/a.py"),
            "old_string": "x",
            "new_string": "email = 'someone@private.net'",
        },
    }
    proc = run_hook(project, "troupe_pii_scrub.py", payload)
    out = json.loads(proc.stdout)
    updated = out["hookSpecificOutput"]["updatedInput"]
    assert "someone@private.net" not in updated["new_string"]
    assert updated["old_string"] == "x"  # untouched


def test_pii_scrub_respects_disabled_flag(project: Path) -> None:
    update_policy(project, piiScrub={"enabled": False})
    payload = write_payload(project, "a.md", content="mail me: someone@private.net")
    proc = run_hook(project, "troupe_pii_scrub.py", payload)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ── review gate ──────────────────────────────────────────────────────


def completed(project_dir: Path, name: str = "Ship auth module") -> dict:
    return {
        "hook_event_name": "TaskCompleted",
        "cwd": str(project_dir),
        "task_name": name,
        "task_status": "completed",
    }


def test_review_gate_disabled_by_default(project: Path) -> None:
    proc = run_hook(project, "troupe_review_gate.py", completed(project))
    assert proc.returncode == 0


def test_review_gate_blocks_until_marker_exists(project: Path) -> None:
    update_policy(project, reviewGate={"enabled": True})

    proc = run_hook(project, "troupe_review_gate.py", completed(project))
    assert proc.returncode == 2
    assert ".troupe/approvals/ship-auth-module" in proc.stderr

    marker = project / ".troupe" / "approvals" / "ship-auth-module"
    marker.parent.mkdir(parents=True)
    marker.write_text("approved by kevin\n", encoding="utf-8")

    proc = run_hook(project, "troupe_review_gate.py", completed(project))
    assert proc.returncode == 0


def test_review_gate_pattern_scopes_which_tasks_gate(project: Path) -> None:
    update_policy(project, reviewGate={"enabled": True, "taskPatterns": ["*deploy*"]})
    assert (
        run_hook(project, "troupe_review_gate.py", completed(project, "Write docs")).returncode == 0
    )
    assert (
        run_hook(project, "troupe_review_gate.py", completed(project, "Deploy to prod")).returncode
        == 2
    )


def test_decision_log_skips_gated_completion_then_logs_after_approval(project: Path) -> None:
    update_policy(project, reviewGate={"enabled": True})
    decisions = project / ".troupe" / "decisions.md"

    run_hook(project, "troupe_decision_log.py", completed(project))
    assert "Ship auth module" not in decisions.read_text(encoding="utf-8")

    marker = project / ".troupe" / "approvals" / "ship-auth-module"
    marker.parent.mkdir(parents=True)
    marker.touch()

    run_hook(project, "troupe_decision_log.py", completed(project))
    assert "Ship auth module" in decisions.read_text(encoding="utf-8")


def test_approvals_dir_is_write_protected(project: Path) -> None:
    payload = write_payload(project, ".troupe/approvals/ship-auth-module")
    proc = run_hook(project, "troupe_file_guard.py", payload)
    assert proc.returncode == 2  # agents cannot self-approve


# ── idle nudge ───────────────────────────────────────────────────────


def idle(project_dir: Path, agent: str = "webster", session: str = "s1") -> dict:
    return {
        "hook_event_name": "TeammateIdle",
        "cwd": str(project_dir),
        "session_id": session,
        "agent_id": agent,
        "agent_type": agent,
    }


def test_idle_nudge_is_bounded(project: Path) -> None:
    first = run_hook(project, "troupe_idle_nudge.py", idle(project))
    second = run_hook(project, "troupe_idle_nudge.py", idle(project))
    third = run_hook(project, "troupe_idle_nudge.py", idle(project))
    assert (first.returncode, second.returncode, third.returncode) == (2, 2, 0)
    assert "task list" in first.stderr


def test_idle_nudge_counts_agents_separately(project: Path) -> None:
    run_hook(project, "troupe_idle_nudge.py", idle(project, agent="webster"))
    run_hook(project, "troupe_idle_nudge.py", idle(project, agent="webster"))
    other = run_hook(project, "troupe_idle_nudge.py", idle(project, agent="mason"))
    assert other.returncode == 2


def test_idle_nudge_runtime_state_is_gitignored(project: Path) -> None:
    run_hook(project, "troupe_idle_nudge.py", idle(project))
    gitignore = project / ".troupe" / ".runtime" / ".gitignore"
    assert gitignore.read_text(encoding="utf-8").strip() == "*"


def test_idle_nudge_respects_disabled_flag(project: Path) -> None:
    update_policy(project, idleNudge={"enabled": False})
    proc = run_hook(project, "troupe_idle_nudge.py", idle(project))
    assert proc.returncode == 0


# ── session context ──────────────────────────────────────────────────


def test_session_context_injects_roster_directives_decisions(project: Path) -> None:
    decisions = project / ".troupe" / "decisions.md"
    with decisions.open("a", encoding="utf-8") as f:
        f.write("\n### 2026-07-06: Chose sqlite for Ralph state\n**By:** Wright\n")

    payload = {"hook_event_name": "SessionStart", "cwd": str(project), "source": "startup"}
    proc = run_hook(project, "troupe_session_context.py", payload)
    assert proc.returncode == 0

    out = json.loads(proc.stdout)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "Wright — lead (agent type: wright)" in context
    assert "Standing team rules" in context
    assert "Chose sqlite for Ralph state" in context
    assert len(context) < 10_000


def test_session_context_silent_outside_troupe_project(project: Path, tmp_path_factory) -> None:
    import os
    import subprocess
    import sys

    bare = tmp_path_factory.mktemp("bare")
    script = project / ".claude" / "hooks" / "troupe_session_context.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"cwd": str(bare)}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(bare)},
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ── wiring ───────────────────────────────────────────────────────────


def test_all_governance_hooks_wired(project: Path) -> None:
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    blob = json.dumps(settings["hooks"])
    for script in (
        "troupe_file_guard.py",
        "troupe_pii_scrub.py",
        "troupe_decision_log.py",
        "troupe_review_gate.py",
        "troupe_idle_nudge.py",
        "troupe_session_context.py",
    ):
        assert script in blob, script
    assert set(settings["hooks"]) >= {"PreToolUse", "TaskCompleted", "TeammateIdle", "SessionStart"}
