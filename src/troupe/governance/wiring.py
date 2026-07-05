"""Wire troupe governance hooks into a project's .claude/settings.json.

The hook scripts themselves are emitted from `troupe.templates.hooks` as
self-contained stdlib-only files — a session must never depend on troupe
being installed (or on uv resolution latency) just to run a PreToolUse
check on every file write.
"""

from __future__ import annotations

import json
import os

HOOK_SCRIPTS = (
    "troupe_file_guard.py",
    "troupe_pii_scrub.py",
    "troupe_decision_log.py",
    "troupe_review_gate.py",
    "troupe_idle_nudge.py",
    "troupe_session_context.py",
)

_WRITE_TOOLS_MATCHER = "Write|Edit|NotebookEdit"


def _interpreter() -> str:
    # Chosen at init time by the machine running init. On Windows, `python3`
    # is often the Microsoft Store alias stub, so prefer `python`; everywhere
    # else `python3` is the reliable name.
    return "python" if os.name == "nt" else "python3"


def _hook_command(script: str) -> dict:
    # Exec form (command + args): no shell quoting to get wrong on paths
    # with spaces, and Claude Code expands ${CLAUDE_PROJECT_DIR} itself.
    return {
        "type": "command",
        "command": _interpreter(),
        "args": [f"${{CLAUDE_PROJECT_DIR}}/.claude/hooks/{script}"],
        "timeout": 15,
    }


def desired_hooks() -> dict[str, list[dict]]:
    """The hook entries `troupe init` wires up, keyed by hook event.

    One entry per script (rather than several scripts per entry) so users can
    remove or reorder any single governance concern independently.
    """
    return {
        "PreToolUse": [
            {
                "matcher": _WRITE_TOOLS_MATCHER,
                "hooks": [_hook_command("troupe_file_guard.py")],
            },
            {
                "matcher": _WRITE_TOOLS_MATCHER,
                "hooks": [_hook_command("troupe_pii_scrub.py")],
            },
        ],
        "TaskCompleted": [
            {"hooks": [_hook_command("troupe_decision_log.py")]},
            {"hooks": [_hook_command("troupe_review_gate.py")]},
        ],
        "TeammateIdle": [
            {"hooks": [_hook_command("troupe_idle_nudge.py")]},
        ],
        "SessionStart": [
            {"hooks": [_hook_command("troupe_session_context.py")]},
        ],
    }


def merge_hooks_into_settings(settings: dict) -> bool:
    """Add troupe hook entries to a settings dict if not already present.

    Everything else in the dict is preserved untouched. An entry counts as
    present when any existing hook for that event references the script by
    filename, so users may freely reorganize or edit their entries without
    init re-adding duplicates. Returns True if the dict was modified.
    """
    changed = False
    hooks = settings.setdefault("hooks", {})
    for event, desired_entries in desired_hooks().items():
        entries = hooks.setdefault(event, [])
        for entry in desired_entries:
            script_name = entry["hooks"][0]["args"][0].rsplit("/", 1)[-1]
            if not any(script_name in json.dumps(existing) for existing in entries):
                entries.append(entry)
                changed = True
    return changed
