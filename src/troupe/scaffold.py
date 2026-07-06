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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from string import Template

from troupe.casting.registry import CastMember, PoolEntry, allocate
from troupe.casting.roles import Role, resolve_role
from troupe.charters.compiler import (
    render_agent_definition,
    render_charter,
    render_history,
)
from troupe.discovery.advisor import CastingPlan
from troupe.discovery.profile import (
    profile_to_json,
    render_project_context,
    render_project_summary,
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


def scaffold(
    root: Path, roles: list[str] | None = None, plan: CastingPlan | None = None
) -> ScaffoldResult:
    """Create or complete the troupe scaffold under `root`.

    Two entry paths: a plain `roles` list (generic charters, no project
    context — today's behavior verbatim) or a scan-derived `plan` (specialized
    charters persisted into casting-state, project context seeded into
    charters/histories/team.md, profile.json refreshed). `plan` wins when
    both are given.
    """
    root = root.resolve()
    troupe_dir = root / ".troupe"
    requested: list[tuple[str, Role | None]]
    if plan is not None:
        requested = [(proposal.role.id, proposal.role) for proposal in plan.proposals]
        project_context = render_project_context(plan.profile)
        project_section = "\n## Project\n\n" + render_project_summary(plan.profile) + "\n"
    else:
        requested = [(r.strip().lower(), None) for r in (roles or list(DEFAULT_ROLES)) if r.strip()]
        project_context = ""
        project_section = ""
    result = ScaffoldResult(root=root)
    now = datetime.now(UTC).isoformat(timespec="seconds")

    state = load_state(troupe_dir)
    existing = members_from_state(state)
    result.cast_existing = existing

    missing = _missing_requests(requested, [m.role for m in existing])
    taken = {m.slug for m in existing}
    new_members = [
        replace(member, charter=charter)
        if charter is not None and charter != resolve_role(role_id)
        else member
        for member, (role_id, charter) in zip(
            allocate([role_id for role_id, _ in missing], taken), missing, strict=True
        )
    ]
    result.cast_added = new_members

    for member in new_members:
        record: dict = {
            "name": member.name,
            "role": member.role,
            "craft": member.entry.craft,
            "status": "active",
            "assignedAt": now,
        }
        if member.charter is not None:
            record["charter"] = {
                "title": member.charter.title,
                "expertise": member.charter.expertise,
                "ownership": list(member.charter.ownership),
                "use_hint": member.charter.use_hint,
            }
        state["assignments"][member.slug] = record

    # Per-member files (charter/history are state: never overwritten; the
    # compiled agent definition is derived, but init still won't clobber a
    # user-edited copy — `troupe upgrade` owns refreshing those).
    for member in result.cast:
        agent_dir = troupe_dir / "agents" / member.slug
        _write_if_missing(
            agent_dir / "charter.md",
            render_charter(member, now, project_context=project_context),
            result,
        )
        _write_if_missing(
            agent_dir / "history.md",
            render_history(member, now, project_context=project_context),
            result,
        )
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

    _sync_team_md(troupe_dir / "team.md", result, project_section)

    _write_if_missing(troupe_dir / "policy.json", _shared_template("policy.json"), result)
    for script in HOOK_SCRIPTS:
        _write_if_missing(
            root / ".claude" / "hooks" / script,
            files("troupe.templates").joinpath(f"hooks/{script}").read_text(encoding="utf-8"),
            result,
        )
    _wire_settings(root / ".claude" / "settings.json", result)

    if plan is not None:
        # Derived (like compiled agent defs): refreshed on every scan-aware
        # run, never hand-edited.
        _refresh_file(troupe_dir / "profile.json", profile_to_json(plan.profile), result)

    if new_members:
        _save_state(troupe_dir, state)

    return result


def preview_cast(root: Path, role_ids: list[str]) -> tuple[list[CastMember], list[CastMember]]:
    """Pure preview of what `scaffold` would cast for `role_ids`: (existing
    active members, members that would be newly allocated). Reads state,
    writes nothing — allocation is deterministic, so the preview matches the
    later scaffold exactly."""
    troupe_dir = root.resolve() / ".troupe"
    existing = members_from_state(load_state(troupe_dir))
    missing = _missing_requests([(r, None) for r in role_ids], [m.role for m in existing])
    new_members = allocate([role_id for role_id, _ in missing], {m.slug for m in existing})
    return existing, new_members


# ── state ────────────────────────────────────────────────────────────


def _state_path(troupe_dir: Path) -> Path:
    return troupe_dir / "casting-state.json"


def load_state(troupe_dir: Path) -> dict:
    path = _state_path(troupe_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": STATE_VERSION, "theme": "crafts", "assignments": {}}


def _save_state(troupe_dir: Path, state: dict) -> None:
    path = _state_path(troupe_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")


def members_from_state(state: dict) -> list[CastMember]:
    members = []
    for slug, record in state["assignments"].items():
        if record.get("status") != "active":
            continue
        entry = PoolEntry(
            name=record.get("name", slug.title()),
            craft=record.get("craft", ""),
            affinities=(),
        )
        members.append(
            CastMember(entry=entry, role=record["role"], charter=_charter_from_record(record))
        )
    return members


def _charter_from_record(record: dict) -> Role | None:
    """Rebuild a persisted specialized charter; absence (all pre-scan casts)
    means 'resolve from the catalog', exactly the previous behavior."""
    raw = record.get("charter")
    if not isinstance(raw, dict):
        return None
    base = resolve_role(record["role"])
    return Role(
        id=base.id,
        title=str(raw.get("title", base.title)),
        expertise=str(raw.get("expertise", base.expertise)),
        ownership=tuple(str(item) for item in raw.get("ownership", base.ownership)),
        use_hint=str(raw.get("use_hint", base.use_hint)),
    )


def _missing_requests(
    requested: list[tuple[str, Role | None]], existing: list[str]
) -> list[tuple[str, Role | None]]:
    """Multiset difference on role ids, preserving request order (two 'backend'
    requests against one existing backend yields one more). Each surviving
    request keeps its optional specialized charter."""
    have = Counter(existing)
    missing: list[tuple[str, Role | None]] = []
    for role_id, charter in requested:
        if have[role_id] > 0:
            have[role_id] -= 1
        else:
            missing.append((role_id, charter))
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


def _refresh_file(path: Path, content: str, result: ScaffoldResult) -> None:
    """Write a derived file, overwriting stale content (unlike state files,
    which go through `_write_if_missing`)."""
    existed = path.exists()
    if existed and path.read_text(encoding="utf-8") == content:
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    (result.updated if existed else result.created).append(path)


def _cast_table(cast: list[CastMember]) -> str:
    lines = [
        "| Name | Role | Charter | Status |",
        "|------|------|---------|--------|",
    ]
    for member in cast:
        role = member.effective_role()
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


def _sync_team_md(path: Path, result: ScaffoldResult, project_section: str = "") -> None:
    table = _cast_table(result.cast)
    if not path.exists():
        content = Template(_shared_template("team.md")).substitute(
            cast_table=table, project_section=project_section
        )
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
