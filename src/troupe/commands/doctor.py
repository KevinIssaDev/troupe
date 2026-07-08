"""`troupe doctor` - diagnose a troupe installation.

Failures (exit 1) are things that break the troupe: missing scaffold files,
missing hook scripts, unwired settings. Warnings are degraded-but-working
states (stale hooks, missing policy knobs). Info lines cover optional
environment: the Agent Teams flag, gh, and claude on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

import typer

from troupe.governance.wiring import HOOK_SCRIPTS
from troupe.scaffold import load_state, members_from_state

Status = Literal["ok", "warn", "fail", "info"]

REQUIRED_FILES = (
    "team.md",
    "decisions.md",
    "directives.md",
    "focus.md",
    "wisdom.md",
    "config.json",
    "casting-state.json",
    "policy.json",
)
POLICY_KNOBS = ("protectedPaths", "piiScrub", "reviewGate", "idleNudge")
TEAMS_FLAG = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


@dataclass(frozen=True)
class Check:
    status: Status
    name: str
    detail: str = ""


def run_checks(root: Path) -> list[Check]:
    root = root.resolve()
    troupe_dir = root / ".troupe"
    if not troupe_dir.is_dir():
        return [
            Check("fail", "troupe scaffold", f"no .troupe/ in {root} - run `troupe init` first")
        ]

    checks: list[Check] = []
    checks.extend(_check_scaffold(troupe_dir))
    checks.extend(_check_cast(root, troupe_dir))
    checks.extend(_check_hooks(root))
    checks.extend(_check_settings(root))
    checks.extend(_check_policy(troupe_dir))
    checks.extend(_check_environment(root))
    return checks


# ── scaffold & cast ──────────────────────────────────────────────────


def _check_scaffold(troupe_dir: Path) -> list[Check]:
    missing = [name for name in REQUIRED_FILES if not (troupe_dir / name).is_file()]
    if missing:
        return [
            Check("fail", "troupe scaffold", f"missing {', '.join(missing)} - run `troupe init`")
        ]
    return [Check("ok", "troupe scaffold", "all required .troupe/ files present")]


def _check_cast(root: Path, troupe_dir: Path) -> list[Check]:
    try:
        members = members_from_state(load_state(troupe_dir))
    except (ValueError, KeyError) as exc:
        return [Check("fail", "casting state", f"casting-state.json unreadable: {exc}")]
    if not members:
        return [
            Check(
                "warn",
                "cast",
                "no active members - run /troupe-setup in Claude Code to cast a team",
            )
        ]

    checks = [Check("ok", "cast", f"{len(members)} active member(s)")]
    broken: list[str] = []
    for member in members:
        for path in (
            troupe_dir / "agents" / member.slug / "charter.md",
            troupe_dir / "agents" / member.slug / "history.md",
            root / ".claude" / "agents" / f"{member.slug}.md",
        ):
            if not path.is_file():
                broken.append(path.relative_to(root).as_posix())
    if broken:
        checks.append(
            Check("fail", "cast files", f"missing {', '.join(broken)} - run `troupe init`")
        )
    else:
        checks.append(Check("ok", "cast files", "charter, history, agent definition per member"))
    return checks


# ── hooks & settings ─────────────────────────────────────────────────


def _check_hooks(root: Path) -> list[Check]:
    checks: list[Check] = []
    missing: list[str] = []
    stale: list[str] = []
    for script in HOOK_SCRIPTS:
        path = root / ".claude" / "hooks" / script
        if not path.is_file():
            missing.append(script)
            continue
        current = files("troupe.templates").joinpath(f"hooks/{script}").read_text(encoding="utf-8")
        if path.read_text(encoding="utf-8") != current:
            stale.append(script)
    if missing:
        checks.append(
            Check("fail", "hook scripts", f"missing {', '.join(missing)} - run `troupe upgrade`")
        )
    if stale:
        checks.append(
            Check("warn", "hook scripts", f"outdated: {', '.join(stale)} - run `troupe upgrade`")
        )
    if not missing and not stale:
        checks.append(Check("ok", "hook scripts", f"all {len(HOOK_SCRIPTS)} present and current"))
    return checks


def _check_settings(root: Path) -> list[Check]:
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        return [Check("fail", "settings wiring", "no .claude/settings.json - run `troupe upgrade`")]
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [Check("fail", "settings wiring", f"settings.json is not valid JSON: {exc}")]

    blob = json.dumps(settings.get("hooks", {}))
    unwired = [script for script in HOOK_SCRIPTS if script not in blob]
    if unwired:
        return [
            Check(
                "fail",
                "settings wiring",
                f"not wired: {', '.join(unwired)} - run `troupe upgrade`",
            )
        ]
    checks = [Check("ok", "settings wiring", "all governance hooks wired")]

    interpreters = _troupe_hook_interpreters(settings)
    unresolved = sorted(i for i in interpreters if shutil.which(i) is None)
    if unresolved:
        checks.append(
            Check(
                "warn",
                "hook interpreter",
                f"{', '.join(unresolved)} not on PATH on this machine - hooks will not run",
            )
        )
    elif interpreters:
        checks.append(Check("ok", "hook interpreter", ", ".join(sorted(interpreters))))
    return checks


def _troupe_hook_interpreters(settings: dict) -> set[str]:
    interpreters: set[str] = set()
    for entries in settings.get("hooks", {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
                if not isinstance(hook, dict):
                    continue
                if any("troupe_" in str(arg) for arg in hook.get("args", [])):
                    command = hook.get("command")
                    if isinstance(command, str):
                        interpreters.add(command)
    return interpreters


def _check_policy(troupe_dir: Path) -> list[Check]:
    try:
        policy = json.loads((troupe_dir / "policy.json").read_text(encoding="utf-8"))
    except ValueError as exc:
        return [Check("fail", "policy", f"policy.json is not valid JSON: {exc}")]
    missing = [knob for knob in POLICY_KNOBS if knob not in policy]
    if missing:
        return [
            Check(
                "warn", "policy", f"missing sections: {', '.join(missing)} - run `troupe upgrade`"
            )
        ]
    return [Check("ok", "policy", "all governance sections present")]


# ── environment ──────────────────────────────────────────────────────


def _check_environment(root: Path) -> list[Check]:
    checks: list[Check] = []

    flag = os.environ.get(TEAMS_FLAG)
    if not flag:
        try:
            settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
            flag = settings.get("env", {}).get(TEAMS_FLAG)
        except (OSError, ValueError):
            flag = None
    if flag:
        checks.append(Check("ok", "agent teams", f"{TEAMS_FLAG} is set - teammate mode available"))
    else:
        checks.append(
            Check(
                "info",
                "agent teams",
                f"{TEAMS_FLAG} not set - cast members still work as plain subagents",
            )
        )

    for tool, purpose in (("gh", "Ralph's GitHub polling"), ("claude", "Ralph's headless runs")):
        if shutil.which(tool):
            checks.append(Check("ok", tool, "on PATH"))
        else:
            checks.append(Check("info", tool, f"not on PATH - needed only for {purpose}"))
    return checks


# ── CLI ──────────────────────────────────────────────────────────────

_MARKS: dict[Status, str] = {"ok": "ok", "warn": "warn", "fail": "FAIL", "info": "info"}

PathArg = Annotated[
    Path, typer.Argument(help="Project root to check (defaults to the current directory).")
]


def doctor(path: PathArg = Path()) -> None:
    """Check this project's troupe setup and diagnose issues."""
    checks = run_checks(path)
    for check in checks:
        detail = f" - {check.detail}" if check.detail else ""
        typer.echo(f"[{_MARKS[check.status]:>4}] {check.name}{detail}")

    fails = sum(1 for c in checks if c.status == "fail")
    warns = sum(1 for c in checks if c.status == "warn")
    typer.echo(f"\n{len(checks)} checks: {fails} failure(s), {warns} warning(s).")
    if fails:
        raise typer.Exit(code=1)
