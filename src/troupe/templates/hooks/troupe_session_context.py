#!/usr/bin/env python3
"""Troupe session context — SessionStart hook.

Emitted by `troupe init`; self-contained (stdlib only).

Injects the team into every session (lead, teammates, and subagents all run
SessionStart): the cast roster, the standing directives, and the most recent
decision titles — with pointers to the full files. This is what makes the
troupe *ambient*: no one has to remember to read the team files first.
"""

import json
import os
import sys
from pathlib import Path

MAX_DIRECTIVES_CHARS = 2000
MAX_RECENT_DECISIONS = 5
MAX_TOTAL_CHARS = 9000


def project_root(payload: dict) -> Path | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    return Path(root) if root else None


def roster_lines(troupe_dir: Path) -> list[str]:
    try:
        state = json.loads((troupe_dir / "casting-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lines = []
    for slug, record in state.get("assignments", {}).items():
        if record.get("status") != "active":
            continue
        name = record.get("name", slug.title())
        role = record.get("role", "member")
        lines.append(f"- {name} — {role} (agent type: {slug})")
    return lines


def directives_text(troupe_dir: Path) -> str:
    try:
        text = (troupe_dir / "directives.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > MAX_DIRECTIVES_CHARS:
        text = text[:MAX_DIRECTIVES_CHARS] + "\n… (truncated — read .troupe/directives.md)"
    return text


def recent_decisions(troupe_dir: Path) -> list[str]:
    try:
        text = (troupe_dir / "decisions.md").read_text(encoding="utf-8")
    except OSError:
        return []
    titles = [line[4:].strip() for line in text.splitlines() if line.startswith("### ")]
    return titles[-MAX_RECENT_DECISIONS:]


def build_context(troupe_dir: Path) -> str:
    parts = [
        "This repository has a troupe: a persistent, named AI team. "
        "Its state lives in .troupe/ and its members exist as agent "
        "definitions in .claude/agents/."
    ]
    roster = roster_lines(troupe_dir)
    if roster:
        parts.append("Cast roster:\n" + "\n".join(roster))
        parts.append(
            "When spawning teammates or subagents for project work, use these "
            "cast agent types and address members by their names."
        )
    directives = directives_text(troupe_dir)
    if directives:
        parts.append("Standing team rules (.troupe/directives.md):\n" + directives)
    decisions = recent_decisions(troupe_dir)
    if decisions:
        parts.append(
            "Most recent decisions (full log: .troupe/decisions.md):\n"
            + "\n".join(f"- {t}" for t in decisions)
        )
    context = "\n\n".join(parts)
    if len(context) > MAX_TOTAL_CHARS:
        context = context[:MAX_TOTAL_CHARS] + "\n… (truncated)"
    return context


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    root = project_root(payload)
    if root is None:
        return 0
    troupe_dir = root / ".troupe"
    if not troupe_dir.is_dir():
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": build_context(troupe_dir),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — governance must not break the session
        sys.stderr.write(f"troupe session context: unexpected error: {exc}\n")
        sys.exit(0)
