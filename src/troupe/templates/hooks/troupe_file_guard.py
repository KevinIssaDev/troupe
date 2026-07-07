#!/usr/bin/env python3
"""Troupe file-write guard — PreToolUse hook.

Emitted by `troupe init`; self-contained (stdlib only) so it runs on any
machine with Python 3, no troupe installation required.

Reads the PreToolUse payload on stdin. If the tool is about to write to a
path protected by `.troupe/policy.json`, exits with code 2 (which blocks the
tool call) and explains why on stderr — naming the sanctioned alternative
(`troupe charter`, `troupe cast`, `troupe upgrade`, or "ask the human") for
the default patterns, so a blocked agent has a legitimate path forward
instead of improvising around the block. Any other outcome exits 0.

Pattern semantics: fnmatch-style, matched case-insensitively against the
file's path relative to the project root, with `/` separators. Note that `*`
crosses directory separators (so `.claude/hooks/*` protects nested files
too).

On an unexpected internal error, this hook fails *closed* (exits 2, blocks
the write) rather than open. This is deliberately the opposite of
troupe_review_gate.py's fail-open behavior: a crashed review gate merely
delays marking a task complete, but a crashed file guard defaulting to
"allow" would silently defeat the one thing this hook exists to do —
stop writes to protected governance files — on exactly the malformed or
adversarial inputs most likely to trigger the crash in the first place.
"""

import fnmatch
import json
import os
import sys
from pathlib import Path

WRITE_PATH_KEYS = ("file_path", "notebook_path")

GENERIC_GUIDANCE = (
    "This file is team governance state; do not modify it. "
    "If the change is genuinely needed, ask the human to edit it "
    "directly or to remove the pattern from .troupe/policy.json."
)

_SECRETS_GUIDANCE = (
    "This path looks like credential material. Never write secret material "
    "from a session; ask the human to manage credentials directly."
)

# Actionable guidance per pattern, keyed by the EXACT default pattern strings
# shipped in troupe's templates/policy.json protectedPaths (a drift test in
# the troupe repo pins that correspondence). Lookup lowercases the fired
# pattern; a pattern the user added or edited misses and falls back to
# GENERIC_GUIDANCE.
GUIDANCE = {
    ".troupe/agents/*/charter.md": (
        "Charters are human-approved mandates. Use `troupe charter <name> "
        "--ownership ... --expertise ...` — from a non-interactive session it "
        "stages a proposal the human applies with `troupe charter <name> "
        "--approve`. Do not move mandate content into history.md instead."
    ),
    ".troupe/casting-state.json": (
        "Cast changes go through `troupe cast --add-role <role>` or "
        "`troupe cast --retire <name>`, never direct edits to this file."
    ),
    ".claude/agents/*.md": (
        "Compiled agent definitions are derived files. Change the mandate via "
        "`troupe cast`/`troupe charter`; `troupe upgrade` refreshes these."
    ),
    ".claude/hooks/*": (
        "Hook scripts are troupe-owned and refreshed by `troupe upgrade`; "
        "if one needs to change, ask the human."
    ),
    ".troupe/policy.json": "The governance policy is human-owned; ask the human to change it.",
    ".claude/settings.json": (
        "Settings are human-owned; troupe's hook wiring is merged in by "
        "`troupe init`/`troupe upgrade`."
    ),
    ".troupe/approvals/*": (
        "Approval markers are written by the human review flow, never by agents."
    ),
    ".troupe/config.json": "Troupe configuration is human-owned; ask the human.",
    ".troupe/.runtime/*": "Runtime state is machine-owned; the troupe CLI manages it.",
    ".troupe/reeve-stop": "The reeve stop marker is human-owned; ask the human.",
    ".env": _SECRETS_GUIDANCE,
    ".env.*": _SECRETS_GUIDANCE,
    "*.pem": _SECRETS_GUIDANCE,
    "*id_rsa*": _SECRETS_GUIDANCE,
}


def project_root(payload: dict) -> Path | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    return Path(root) if root else None


def target_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in WRITE_PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def load_patterns(root: Path) -> list[str]:
    policy_path = root / ".troupe" / "policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    patterns = policy.get("protectedPaths", [])
    return [p for p in patterns if isinstance(p, str)]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    raw_target = target_path(payload)
    root = project_root(payload)
    if raw_target is None or root is None:
        return 0

    try:
        rel = Path(raw_target).resolve().relative_to(root.resolve())
    except ValueError:
        return 0  # outside the project root — not ours to police

    rel_posix = rel.as_posix().lower()
    for pattern in load_patterns(root):
        if fnmatch.fnmatch(rel_posix, pattern.lower()):
            guidance = GUIDANCE.get(pattern.lower(), GENERIC_GUIDANCE)
            sys.stderr.write(
                f"troupe file guard: '{rel.as_posix()}' is protected "
                f"(pattern '{pattern}' in .troupe/policy.json). "
                f"{guidance}\n"
            )
            return 2

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — fail closed: this is a security control
        # Unlike troupe_review_gate.py (which fails open because the only
        # cost of a false block is delaying task completion), this hook's
        # entire job is to stop writes to protected files. An unhandled
        # crash defaulting to "allow" would silently defeat that guarantee
        # on exactly the inputs most likely to be malformed or adversarial.
        # So: block the write, explain why on stderr, exit 2.
        sys.stderr.write(
            f"troupe file guard: unexpected error ({exc}); blocking this write "
            "defensively. If this keeps happening, ask the human to investigate "
            "the hook (.claude/hooks/troupe_file_guard.py) or the write will "
            "keep being refused.\n"
        )
        sys.exit(2)
