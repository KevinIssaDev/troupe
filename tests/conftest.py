"""Shared fixtures and helpers for hook tests.

Hook tests run the *emitted* scripts as subprocesses with a payload on
stdin — the same way Claude Code invokes them. Exit code 2 blocks; 0 allows.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from troupe.scaffold import scaffold


@pytest.fixture
def project(tmp_path: Path) -> Path:
    scaffold(tmp_path, roles=["lead", "backend", "frontend", "tester"])
    return tmp_path


def run_hook(project_dir: Path, script: str, payload: dict) -> subprocess.CompletedProcess[str]:
    script_path = project_dir / ".claude" / "hooks" / script
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def write_payload(project_dir: Path, rel: str, tool: str = "Write", content: str = "x") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "cwd": str(project_dir),
        "tool_name": tool,
        "tool_input": {"file_path": str(project_dir / rel), "content": content},
    }


def update_policy(project_dir: Path, **sections) -> None:
    """Overlay sections onto the project's .troupe/policy.json."""
    path = project_dir / ".troupe" / "policy.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    for key, value in sections.items():
        if isinstance(value, dict) and isinstance(policy.get(key), dict):
            policy[key].update(value)
        else:
            policy[key] = value
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
