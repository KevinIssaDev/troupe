"""Render cast-member files from package templates.

Three artifacts per cast member:
  charter.md    — human-editable role definition, lives in .troupe/agents/{slug}/
  history.md    — accumulated knowledge, lives next to the charter
  {slug}.md     — compiled Claude Code subagent definition, lives in .claude/agents/;
                  works as an Agent Teams teammate type and as a plain subagent.
"""

from __future__ import annotations

from importlib.resources import files
from string import Template

from troupe.casting.registry import CastMember
from troupe.casting.roles import resolve_role


def _template(name: str) -> Template:
    text = files("troupe.templates").joinpath(name).read_text(encoding="utf-8")
    return Template(text)


def _member_context(member: CastMember, created_at: str) -> dict[str, str]:
    role = resolve_role(member.role)
    return {
        "name": member.name,
        "slug": member.slug,
        "craft": member.entry.craft,
        "role_title": role.title,
        "expertise": role.expertise,
        "use_hint": role.use_hint,
        "ownership_bullets": "\n".join(f"- {item}" for item in role.ownership),
        "created_at": created_at,
    }


def render_charter(member: CastMember, created_at: str) -> str:
    return _template("charter.md").substitute(_member_context(member, created_at))


def render_history(member: CastMember, created_at: str) -> str:
    return _template("history.md").substitute(_member_context(member, created_at))


def render_agent_definition(member: CastMember, created_at: str) -> str:
    return _template("agent.md").substitute(_member_context(member, created_at))
