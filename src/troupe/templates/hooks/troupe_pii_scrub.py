#!/usr/bin/env python3
"""Troupe PII scrub — PreToolUse hook.

Emitted by `troupe init`; self-contained (stdlib only).

Scans content about to be written (Write/Edit/NotebookEdit) for email
addresses and redacts them in place via the hook's `updatedInput` output —
the write proceeds, scrubbed, instead of being blocked outright. Addresses
matching the `piiScrub.allowlist` patterns in `.troupe/policy.json` are left
alone. When nothing needs redacting, the hook stays silent.
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
REDACTION = "[email-redacted]"
CONTENT_KEYS = ("content", "new_string", "new_source")


def project_root(payload: dict) -> Path | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    return Path(root) if root else None


def load_config(root: Path) -> dict:
    try:
        policy = json.loads((root / ".troupe" / "policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    config = policy.get("piiScrub")
    return config if isinstance(config, dict) else {}


def redact(text: str, allowlist: list[str]) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        email = match.group(0)
        if any(fnmatch.fnmatch(email.lower(), pattern) for pattern in allowlist):
            return email
        count += 1
        return REDACTION

    return EMAIL_RE.sub(replace, text), count


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
    allowlist = [p.lower() for p in config.get("allowlist", []) if isinstance(p, str)]

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    updated = dict(tool_input)
    total = 0
    for key in CONTENT_KEYS:
        value = updated.get(key)
        if isinstance(value, str) and value:
            scrubbed, count = redact(value, allowlist)
            if count:
                updated[key] = scrubbed
                total += count

    if total == 0:
        return 0

    noun = "address" if total == 1 else "addresses"
    print(
        json.dumps(
            {
                "systemMessage": f"troupe PII scrub: redacted {total} email {noun} before write.",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": (
                        f"Redacted {total} email {noun} per .troupe/policy.json piiScrub."
                    ),
                    "updatedInput": updated,
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — governance must not break the session
        sys.stderr.write(f"troupe pii scrub: unexpected error: {exc}\n")
        sys.exit(0)
