"""Scaffolding for `troupe init` — creates .troupe/ state and .claude/ agent definitions.

Idempotency contract: files that hold user or team state (charters, histories,
team.md, decisions.md, directives.md, config.json) are never overwritten.
casting-state.json is rewritten only when new members are cast. Re-running
init fills gaps and adds newly requested roles; it never renames or removes
an existing cast member.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from string import Template

from troupe.casting.registry import CastMember, PoolEntry, allocate
from troupe.casting.roles import resolve_role
from troupe.charters.compiler import (
    render_agent_definition,
    render_charter,
    render_history,
)
from troupe.governance.wiring import HOOK_SCRIPTS, merge_hooks_into_settings

DEFAULT_ROLES = ("lead", "backend", "frontend", "tester")
STATE_VERSION = 1


@dataclass
class ScaffoldResult:
    root: Path
    created: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    cast_added: list[CastMember] = field(default_factory=list)
    cast_existing: list[CastMember] = field(default_factory=list)

    @property
    def cast(self) -> list[CastMember]:
        return [*self.cast_existing, *self.cast_added]


def scaffold(root: Path, roles: list[str] | None = None) -> ScaffoldResult:
    """Create or complete the troupe scaffold under `root`."""
    root = root.resolve()
    troupe_dir = root / ".troupe"
    requested = [r.strip().lower() for r in (roles or list(DEFAULT_ROLES)) if r.strip()]
    result = ScaffoldResult(root=root)
    now = datetime.now(UTC).isoformat(timespec="seconds")

    state = _load_state(troupe_dir)
    existing = _members_from_state(state)
    result.cast_existing = existing

    missing_roles = _missing_roles(requested, [m.role for m in existing])
    taken = {m.slug for m in existing}
    new_members = allocate(missing_roles, taken)
    result.cast_added = new_members

    for member in new_members:
        state["assignments"][member.slug] = {
            "name": member.name,
            "role": member.role,
            "craft": member.entry.craft,
            "status": "active",
            "assignedAt": now,
        }

    # Per-member files (charter/history are state: never overwritten; the
    # compiled agent definition is derived, but init still won't clobber a
    # user-edited copy — `troupe upgrade` owns refreshing those).
    for member in result.cast:
        agent_dir = troupe_dir / "agents" / member.slug
        _write_if_missing(agent_dir / "charter.md", render_charter(member, now), result)
        _write_if_missing(agent_dir / "history.md", render_history(member, now), result)
        _write_if_missing(
            root / ".claude" / "agents" / f"{member.slug}.md",
            render_agent_definition(member, now),
            result,
        )

    _write_if_missing(troupe_dir / "decisions.md", _shared_template("decisions.md"), result)
    _write_if_missing(troupe_dir / "directives.md", _shared_template("directives.md"), result)
    _write_if_missing(
        troupe_dir / "config.json",
        json.dumps({"version": STATE_VERSION, "theme": state["theme"], "createdAt": now}, indent=2)
        + "\n",
        result,
    )

    _sync_team_md(troupe_dir / "team.md", result)

    _write_if_missing(troupe_dir / "policy.json", _shared_template("policy.json"), result)
    for script in HOOK_SCRIPTS:
        _write_if_missing(
            root / ".claude" / "hooks" / script,
            files("troupe.templates").joinpath(f"hooks/{script}").read_text(encoding="utf-8"),
            result,
        )
    _wire_settings(root / ".claude" / "settings.json", result)

    if new_members:
        _save_state(troupe_dir, state)

    return result


# ── state ────────────────────────────────────────────────────────────


def _state_path(troupe_dir: Path) -> Path:
    return troupe_dir / "casting-state.json"


def _load_state(troupe_dir: Path) -> dict:
    path = _state_path(troupe_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": STATE_VERSION, "theme": "crafts", "assignments": {}}


def _save_state(troupe_dir: Path, state: dict) -> None:
    path = _state_path(troupe_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")


def _members_from_state(state: dict) -> list[CastMember]:
    members = []
    for slug, record in state["assignments"].items():
        if record.get("status") != "active":
            continue
        entry = PoolEntry(
            name=record.get("name", slug.title()),
            craft=record.get("craft", ""),
            affinities=(),
        )
        members.append(CastMember(entry=entry, role=record["role"]))
    return members


def _missing_roles(requested: list[str], existing: list[str]) -> list[str]:
    """Multiset difference, preserving request order (two 'backend' requests
    against one existing backend yields one more)."""
    have = Counter(existing)
    missing: list[str] = []
    for role in requested:
        if have[role] > 0:
            have[role] -= 1
        else:
            missing.append(role)
    return missing


# ── files ────────────────────────────────────────────────────────────


def _shared_template(name: str) -> str:
    return files("troupe.templates").joinpath(name).read_text(encoding="utf-8")


def _write_if_missing(path: Path, content: str, result: ScaffoldResult) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    result.created.append(path)


def _cast_table(cast: list[CastMember]) -> str:
    lines = [
        "| Name | Role | Charter | Status |",
        "|------|------|---------|--------|",
    ]
    for member in cast:
        role = resolve_role(member.role)
        lines.append(
            f"| {member.name} | {role.title} | `.troupe/agents/{member.slug}/charter.md` | active |"
        )
    return "\n".join(lines)


def _wire_settings(path: Path, result: ScaffoldResult) -> None:
    """Create .claude/settings.json, or merge troupe hook wiring into an
    existing one — preserving everything the user already has in it."""
    settings: dict = {}
    existed = path.exists()
    if existed:
        settings = json.loads(path.read_text(encoding="utf-8"))
    changed = merge_hooks_into_settings(settings)
    if not changed:
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
    (result.updated if existed else result.created).append(path)


def _sync_team_md(path: Path, result: ScaffoldResult) -> None:
    table = _cast_table(result.cast)
    if not path.exists():
        content = Template(_shared_template("team.md")).substitute(cast_table=table)
        _write_if_missing(path, content, result)
        return
    if not result.cast_added:
        result.skipped.append(path)
        return
    # Regenerate only the roster table inside the existing "## Cast" section,
    # leaving everything the user wrote around it untouched.
    text = path.read_text(encoding="utf-8")
    marker = "## Cast"
    start = text.find(marker)
    if start == -1:
        result.skipped.append(path)
        return
    section_body_start = start + len(marker)
    next_section = text.find("\n## ", section_body_start)
    tail = text[next_section:] if next_section != -1 else ""
    updated = text[:section_body_start] + "\n\n" + table + "\n" + tail
    path.write_text(updated, encoding="utf-8", newline="\n")
    result.created.append(path)
