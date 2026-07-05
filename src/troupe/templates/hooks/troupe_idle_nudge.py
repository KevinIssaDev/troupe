#!/usr/bin/env python3
"""Troupe idle nudge — TeammateIdle hook.

Emitted by `troupe init`; self-contained (stdlib only).

When a teammate is about to go idle, exit code 2 sends it back to work with
the stderr text as feedback. Unbounded nudging would keep teammates alive
forever, so this hook is strictly bounded: at most `idleNudge.maxNudgesPerAgent`
nudges (default 2) per agent per session, tracked in
`.troupe/.runtime/idle-nudges.json` (a runtime file, auto-gitignored).
"""

import contextlib
import json
import os
import sys
from pathlib import Path

NUDGE = (
    "troupe idle nudge: before going idle, do a last sweep. "
    "1) Check the shared task list for pending, unblocked tasks that fit your "
    "charter and claim one if it exists. "
    "2) Confirm you recorded team-relevant choices in .troupe/decisions.md and "
    "durable learnings in your history file, as your charter requires. "
    "If you have genuinely finished both sweeps, say so and stop.\n"
)


def project_root(payload: dict) -> Path | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    return Path(root) if root else None


def load_config(root: Path) -> dict:
    try:
        policy = json.loads((root / ".troupe" / "policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    config = policy.get("idleNudge")
    return config if isinstance(config, dict) else {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    root = project_root(payload)
    if root is None:
        return 0

    config = load_config(root)
    if not config.get("enabled", False):
        return 0
    try:
        cap = int(config.get("maxNudgesPerAgent", 2))
    except (TypeError, ValueError):
        cap = 2

    agent = payload.get("agent_id") or payload.get("agent_type") or "teammate"
    key = f"{payload.get('session_id', '')}:{agent}"

    runtime_dir = root / ".troupe" / ".runtime"
    state_path = runtime_dir / "idle-nudges.json"
    counts: dict = {}
    with contextlib.suppress(OSError, ValueError):
        counts = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(counts, dict):
        counts = {}

    used = counts.get(key, 0)
    if not isinstance(used, int) or used >= cap:
        return 0

    counts[key] = used + 1
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        gitignore = runtime_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")
        state_path.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return 0  # can't track the bound — do not risk an unbounded nudge loop

    sys.stderr.write(NUDGE)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — governance must not break the session
        sys.stderr.write(f"troupe idle nudge: unexpected error: {exc}\n")
        sys.exit(0)
