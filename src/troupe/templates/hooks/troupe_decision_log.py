#!/usr/bin/env python3
"""Troupe decision logger — TaskCompleted hook.

Emitted by `troupe init`; self-contained (stdlib only).

Appends a structured entry to `.troupe/decisions.md` whenever a task is
marked complete, so the shared log accumulates a record of finished work
without anyone remembering to write it. Cast members still record real
architectural decisions themselves, per their charters — this hook only
guarantees the baseline trail exists.

Governance must never break the session: this hook always exits 0, even on
unexpected errors (reported to stderr, which lands in the debug log).
"""

import fnmatch
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def project_root(payload: dict) -> Path | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    return Path(root) if root else None


def review_gate_blocks(root: Path, payload: dict) -> bool:
    """Mirror of troupe_review_gate.py's verdict. Hooks for one event run in
    parallel, so when the gate is about to reject this completion, the logger
    must not record it as done — the entry will be written on the retry that
    passes the gate."""
    try:
        policy = json.loads((root / ".troupe" / "policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    gate = policy.get("reviewGate")
    if not isinstance(gate, dict) or not gate.get("enabled", False):
        return False
    name = str(payload.get("task_name") or "").strip()
    if not name:
        return False
    patterns = [p for p in gate.get("taskPatterns", ["*"]) if isinstance(p, str)]
    if not any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns):
        return False
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "task"
    return not (root / ".troupe" / "approvals" / slug).is_file()


def format_entry(payload: dict) -> str:
    date = datetime.now().strftime("%Y-%m-%d")
    name = str(payload.get("task_name") or "unnamed task").strip()
    status = str(payload.get("task_status") or "completed").strip()
    description = str(payload.get("task_description") or "").strip()
    what = f'Task "{name}" was marked {status}.'
    if description:
        what += f" Scope: {description}"
    return (
        f"\n### {date}: Completed — {name}\n**By:** troupe (TaskCompleted hook)\n**What:** {what}\n"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    root = project_root(payload)
    if root is None:
        return 0

    decisions = root / ".troupe" / "decisions.md"
    if not decisions.is_file():
        return 0  # not a troupe project (or log removed) — nothing to do

    if review_gate_blocks(root, payload):
        return 0  # completion is being rejected by the review gate — don't log it

    try:
        with decisions.open("a", encoding="utf-8", newline="\n") as f:
            f.write(format_entry(payload))
    except OSError as exc:
        sys.stderr.write(f"troupe decision log: could not append: {exc}\n")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — governance must not break the session
        sys.stderr.write(f"troupe decision log: unexpected error: {exc}\n")
        sys.exit(0)
