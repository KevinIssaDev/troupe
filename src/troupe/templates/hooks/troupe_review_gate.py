#!/usr/bin/env python3
"""Troupe review gate — TaskCompleted hook.

Emitted by `troupe init`; self-contained (stdlib only).

When `reviewGate.enabled` is true in `.troupe/policy.json`, a task whose
name matches `reviewGate.taskPatterns` cannot be marked complete until a
human drops an approval marker at `.troupe/approvals/{task-slug}`. The
approvals directory is in the file guard's protected paths, so agents
cannot approve their own work.

Disabled by default — enable it per project when you want a human sign-off
step in the loop.
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path


def project_root(payload: dict) -> Path | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    return Path(root) if root else None


def load_gate(root: Path) -> dict:
    try:
        policy = json.loads((root / ".troupe" / "policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    gate = policy.get("reviewGate")
    return gate if isinstance(gate, dict) else {}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "task"


def gate_verdict(root: Path, payload: dict) -> tuple[bool, str, Path | None]:
    """Returns (blocked, task_name, marker_path)."""
    gate = load_gate(root)
    name = str(payload.get("task_name") or "").strip()
    if not gate.get("enabled", False) or not name:
        return False, name, None
    patterns = [p for p in gate.get("taskPatterns", ["*"]) if isinstance(p, str)]
    if not any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns):
        return False, name, None
    marker = root / ".troupe" / "approvals" / slugify(name)
    return not marker.is_file(), name, marker


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    root = project_root(payload)
    if root is None:
        return 0

    blocked, name, marker = gate_verdict(root, payload)
    if not blocked or marker is None:
        return 0

    rel = marker.relative_to(root).as_posix()
    sys.stderr.write(
        f"troupe review gate: task '{name}' requires human approval before it can be "
        f"marked complete. Ask the human to review the work and create the marker file "
        f"'{rel}' (its content does not matter), then complete the task again. "
        "Do not create this file yourself — the approvals directory is write-protected "
        "for agents, and self-approval defeats the review gate.\n"
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — fail open: never wedge task completion
        sys.stderr.write(f"troupe review gate: unexpected error: {exc}\n")
        sys.exit(0)
