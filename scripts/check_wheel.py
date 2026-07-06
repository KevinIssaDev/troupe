"""Verify the built wheel ships all package data the CLI depends on.

Templates are read via importlib.resources at runtime; a wheel missing them
installs fine and then breaks on first `troupe init`. This check fails the
build instead. Usage: python scripts/check_wheel.py <dist-dir>
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REQUIRED = (
    "troupe/casting/names.json",
    "troupe/templates/agent.md",
    "troupe/templates/charter.md",
    "troupe/templates/history.md",
    "troupe/templates/team.md",
    "troupe/templates/decisions.md",
    "troupe/templates/directives.md",
    "troupe/templates/policy.json",
    "troupe/templates/hooks/troupe_file_guard.py",
    "troupe/templates/hooks/troupe_pii_scrub.py",
    "troupe/templates/hooks/troupe_decision_log.py",
    "troupe/templates/hooks/troupe_review_gate.py",
    "troupe/templates/hooks/troupe_idle_nudge.py",
    "troupe/templates/hooks/troupe_session_context.py",
)


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        print(f"no wheel found in {dist}", file=sys.stderr)
        return 1
    wheel = wheels[-1]
    names = set(zipfile.ZipFile(wheel).namelist())
    missing = [required for required in REQUIRED if required not in names]
    if missing:
        print(f"{wheel.name} is missing package data:", file=sys.stderr)
        for name in missing:
            print(f"  {name}", file=sys.stderr)
        return 1
    print(f"{wheel.name}: all {len(REQUIRED)} package-data files present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
