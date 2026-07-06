"""Builds the work-context prompt Reeve feeds to a headless Claude session."""

from __future__ import annotations

from pathlib import Path

from troupe.reeve.poller import Issue

MAX_BODY_CHARS = 4000
MAX_DIRECTIVES_CHARS = 2000
MAX_RECENT_DECISIONS = 5

DISPATCH_PROMPT = (
    "You are a member of this repository's troupe (persistent AI team), dispatched "
    "by Reeve, the team's watch loop, to work a GitHub issue unattended. Your full "
    "work context follows on stdin. Follow it exactly."
)


def build_context(
    target: Issue,
    board: list[Issue],
    troupe_dir: Path,
    execute: bool,
) -> str:
    sections = [
        "# Work Context (from Reeve)",
        _target_section(target),
        _board_section(target, board),
        _directives_section(troupe_dir),
        _decisions_section(troupe_dir),
        _rules_section(target, execute),
    ]
    return "\n\n".join(section for section in sections if section)


def _target_section(target: Issue) -> str:
    body = target.body.strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n... (truncated - read the full issue with gh issue view)"
    lines = [f"## Your assignment: issue #{target.number} - {target.title}"]
    if target.labels:
        lines.append(f"Labels: {', '.join(target.labels)}")
    if target.url:
        lines.append(f"URL: {target.url}")
    lines.append("")
    lines.append(body if body else "(no issue body)")
    return "\n".join(lines)


def _board_section(target: Issue, board: list[Issue]) -> str:
    others = [issue for issue in board if issue.number != target.number]
    if not others:
        return ""
    lines = ["## The rest of the board (context only - do NOT work these)"]
    lines.extend(f"- #{issue.number} {issue.title}" for issue in others[:15])
    return "\n".join(lines)


def _directives_section(troupe_dir: Path) -> str:
    try:
        text = (troupe_dir / "directives.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > MAX_DIRECTIVES_CHARS:
        text = text[:MAX_DIRECTIVES_CHARS] + "\n... (truncated - read .troupe/directives.md)"
    return "## Standing team rules (.troupe/directives.md)\n\n" + text


def _decisions_section(troupe_dir: Path) -> str:
    try:
        text = (troupe_dir / "decisions.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    titles = [line[4:].strip() for line in text.splitlines() if line.startswith("### ")]
    if not titles:
        return ""
    recent = "\n".join(f"- {title}" for title in titles[-MAX_RECENT_DECISIONS:])
    return (
        "## Recent team decisions (full log: .troupe/decisions.md - read it before "
        "making architectural choices)\n\n" + recent
    )


def _rules_section(target: Issue, execute: bool) -> str:
    lines = [
        "## Rules of engagement",
        "",
        f"1. Work ONLY issue #{target.number}. The rest of the board is context.",
        "2. Read .troupe/decisions.md before making choices; record any team-relevant "
        "decision there in the documented entry format.",
        "3. Follow the standing rules above at all times.",
        "4. Success criteria: the change is complete, tests pass if the project has them, "
        "and your work matches existing project conventions.",
        "5. If you are blocked, need credentials, or the issue requires a judgment call "
        "a human should make: STOP. Do not guess.",
    ]
    if execute:
        lines.append(
            f"6. When you finish (or stop blocked), comment your outcome on the issue: "
            f"`gh issue comment {target.number} --body <summary>`. Summarize what you did "
            "or why you stopped, and list files you changed. Do NOT close the issue - "
            "a human verifies and closes."
        )
    return "\n".join(lines)
