"""Governance hook tests.

Each test scaffolds a real project into tmp_path, then runs the *emitted*
hook script as a subprocess with a payload on stdin — the same way Claude
Code invokes it. Exit code 2 blocks; exit code 0 allows.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import run_hook, write_payload
from troupe.scaffold import scaffold

# ── file guard ───────────────────────────────────────────────────────


def test_guard_blocks_protected_state(project: Path) -> None:
    proc = run_hook(
        project, "troupe_file_guard.py", write_payload(project, ".troupe/casting-state.json")
    )
    assert proc.returncode == 2
    assert "protected" in proc.stderr
    assert "policy.json" in proc.stderr


def test_guard_blocks_charters(project: Path) -> None:
    proc = run_hook(
        project,
        "troupe_file_guard.py",
        write_payload(project, ".troupe/agents/wright/charter.md", tool="Edit"),
    )
    assert proc.returncode == 2


def test_guard_blocks_compiled_agent_definitions(project: Path) -> None:
    proc = run_hook(
        project,
        "troupe_file_guard.py",
        write_payload(project, ".claude/agents/wright.md", tool="Edit"),
    )
    assert proc.returncode == 2


def test_guard_blocks_env_files_case_insensitively(project: Path) -> None:
    proc = run_hook(project, "troupe_file_guard.py", write_payload(project, ".ENV"))
    assert proc.returncode == 2


def test_guard_blocks_nested_hook_scripts(project: Path) -> None:
    proc = run_hook(
        project, "troupe_file_guard.py", write_payload(project, ".claude/hooks/sub/evil.py")
    )
    assert proc.returncode == 2


def test_guard_allows_ordinary_source_files(project: Path) -> None:
    proc = run_hook(project, "troupe_file_guard.py", write_payload(project, "src/app.py"))
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_guard_allows_history_and_decisions(project: Path) -> None:
    for rel in (".troupe/agents/wright/history.md", ".troupe/decisions.md"):
        proc = run_hook(project, "troupe_file_guard.py", write_payload(project, rel))
        assert proc.returncode == 0, rel


def test_guard_ignores_non_write_tools(project: Path) -> None:
    payload = {
        "hook_event_name": "PreToolUse",
        "cwd": str(project),
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    }
    proc = run_hook(project, "troupe_file_guard.py", payload)
    assert proc.returncode == 0


def test_guard_ignores_paths_outside_project(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("elsewhere") / ".env"
    payload = write_payload(project, "unused")
    payload["tool_input"]["file_path"] = str(outside)
    proc = run_hook(project, "troupe_file_guard.py", payload)
    assert proc.returncode == 0


def test_guard_survives_malformed_payload(project: Path) -> None:
    script = project / ".claude" / "hooks" / "troupe_file_guard.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        input="not json{",
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        timeout=30,
    )
    assert proc.returncode == 0


# ── decision logger ──────────────────────────────────────────────────


def completed_payload(project_dir: Path, name: str = "Ship login page") -> dict:
    return {
        "hook_event_name": "TaskCompleted",
        "cwd": str(project_dir),
        "task_name": name,
        "task_description": "Build and test the login page",
        "task_status": "completed",
    }


def test_decision_log_appends_entry(project: Path) -> None:
    proc = run_hook(project, "troupe_decision_log.py", completed_payload(project))
    assert proc.returncode == 0
    text = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert "Completed — Ship login page" in text
    assert "**By:** troupe (TaskCompleted hook)" in text
    assert "marked completed" in text


def test_decision_log_accumulates(project: Path) -> None:
    run_hook(project, "troupe_decision_log.py", completed_payload(project, "task one"))
    run_hook(project, "troupe_decision_log.py", completed_payload(project, "task two"))
    text = (project / ".troupe" / "decisions.md").read_text(encoding="utf-8")
    assert text.index("task one") < text.index("task two")


def test_decision_log_noop_without_troupe(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # copy the emitted script into a non-troupe dir: must exit 0, create nothing
    bare = tmp_path_factory.mktemp("no-troupe")
    script = (project / ".claude" / "hooks" / "troupe_decision_log.py").read_text(encoding="utf-8")
    loose = bare / "loose.py"
    loose.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(loose)],
        input=json.dumps({"task_name": "x", "cwd": str(bare)}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(bare)},
        timeout=30,
    )
    assert proc.returncode == 0
    assert not (bare / ".troupe").exists()


# ── settings wiring ──────────────────────────────────────────────────


def test_settings_wired_on_init(project: Path) -> None:
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    events = settings["hooks"]
    assert any("troupe_file_guard.py" in json.dumps(e) for e in events["PreToolUse"])
    assert any("troupe_decision_log.py" in json.dumps(e) for e in events["TaskCompleted"])
    matcher = events["PreToolUse"][0]["matcher"]
    assert "Write" in matcher and "Edit" in matcher


def test_settings_merge_preserves_existing(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {
        "permissions": {"allow": ["Bash(npm test)"]},
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-check"}]}
            ]
        },
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing), encoding="utf-8")

    scaffold(tmp_path)

    merged = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert merged["permissions"] == {"allow": ["Bash(npm test)"]}
    pre = merged["hooks"]["PreToolUse"]
    assert any("my-check" in json.dumps(e) for e in pre)
    assert any("troupe_file_guard.py" in json.dumps(e) for e in pre)


def test_settings_merge_is_idempotent(project: Path) -> None:
    before = (project / ".claude" / "settings.json").read_text(encoding="utf-8")
    scaffold(project)
    after = (project / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert before == after
