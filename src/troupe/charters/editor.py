"""Structured charter edits — the logic behind `troupe charter`.

System-of-record fact shaping everything here: the compiled agent definition
(`render_agent_definition`) renders from `member.effective_role()` — i.e. the
`charter` record in casting-state.json, or the static catalog — never from
charter.md prose, and `troupe upgrade` re-renders agent definitions from
casting-state on every run. So a charter edit MUST persist into the
casting-state `charter` record or upgrade silently reverts it; charter.md and
`.claude/agents/{slug}.md` are projections of that record.

Apply semantics are all-or-nothing: `prepare_edit` computes and validates
every write (including the surgical charter.md rewrite, which touches only
the anchors of fields that actually changed) before anything is written; a
missing anchor raises and nothing is touched anywhere.

Proposals: off a TTY, `troupe charter` never applies — it stages a JSON
proposal at `.troupe/proposals/charter-{slug}.json` (deliberately NOT a
protected path: agents may stage) that a human later applies from a real
terminal with `--approve`. The approve path re-renders the diff from the
proposal file at approve time, so a proposal tampered with after staging is
what the human actually sees.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from troupe.casting.registry import CastMember, PoolEntry
from troupe.casting.roles import Role, resolve_role
from troupe.charters.compiler import render_agent_definition
from troupe.governance.writes import append_decision_entry, backup_and_write
from troupe.scaffold import (
    _charter_from_record,
    _rewrite_cast_table,
    load_state,
    members_from_state,
)


class CharterEditError(Exception):
    """Base for charter-edit failures the CLI maps to exit code 1."""


class UnknownMemberError(CharterEditError):
    """The named cast member does not exist or is retired."""


class AnchorMissingError(CharterEditError):
    """charter.md lacks an anchor a changed field needs; nothing was written."""


class NoPendingProposalError(CharterEditError):
    """--approve/--reject with no staged proposal for that member."""


@dataclass(frozen=True)
class CharterFields:
    """The structured field overrides one invocation carries. `None` means
    "not provided" — an empty string is a deliberate (if odd) value.
    `ownership` REPLACES the whole list, never appends."""

    title: str | None = None
    expertise: str | None = None
    ownership: tuple[str, ...] | None = None
    use_hint: str | None = None

    def provided(self) -> bool:
        return any(
            v is not None for v in (self.title, self.expertise, self.ownership, self.use_hint)
        )

    def to_dict(self) -> dict:
        """Only the provided fields, JSON-shaped (ownership as a list)."""
        out: dict = {}
        if self.title is not None:
            out["title"] = self.title
        if self.expertise is not None:
            out["expertise"] = self.expertise
        if self.ownership is not None:
            out["ownership"] = list(self.ownership)
        if self.use_hint is not None:
            out["use_hint"] = self.use_hint
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> CharterFields:
        """Rebuild from a staged proposal's `fields`. Defensive coercion: the
        proposal file is agent-writable by design, so shapes aren't trusted —
        but content isn't sanitized away either, because the approve-time diff
        shows the human exactly what the file now says."""
        ownership = raw.get("ownership")
        return cls(
            title=str(raw["title"]) if "title" in raw else None,
            expertise=str(raw["expertise"]) if "expertise" in raw else None,
            ownership=tuple(str(item) for item in ownership)
            if isinstance(ownership, list)
            else None,
            use_hint=str(raw["use_hint"]) if "use_hint" in raw else None,
        )


@dataclass
class CharterEdit:
    """Everything an apply will write, fully computed and validated upfront."""

    root: Path
    troupe_dir: Path
    slug: str
    member_name: str
    state: dict
    old_role: Role
    new_role: Role
    charter_path: Path
    old_charter_text: str
    new_charter_text: str

    @property
    def changed(self) -> bool:
        return self.new_role != self.old_role

    @property
    def title_changed(self) -> bool:
        return self.new_role.title != self.old_role.title


def prepare_edit(root: Path, name: str, fields: CharterFields) -> CharterEdit:
    """Validate the member and compute every write, writing nothing.

    Raises UnknownMemberError for a missing or retired member and
    AnchorMissingError when charter.md lacks an anchor a changed field
    needs — in both cases zero files have been touched."""
    root = root.resolve()
    troupe_dir = root / ".troupe"
    state = load_state(troupe_dir)
    slug = name.strip().lower()
    record = state["assignments"].get(slug)
    if record is None:
        raise UnknownMemberError(f"no cast member named '{name}'")
    if record.get("status") != "active":
        raise UnknownMemberError(
            f"'{name}' is retired; recast the role with `troupe cast --add-role` "
            "before editing its charter"
        )

    # Members cast via plain --roles carry no `charter` record: build one from
    # the catalog role as the base, then apply the overrides on top.
    old_role = _charter_from_record(record) or resolve_role(record["role"])
    overrides = fields.to_dict()
    if "ownership" in overrides:
        overrides["ownership"] = tuple(overrides["ownership"])
    new_role = replace(old_role, **overrides)

    member_name = record.get("name", slug.title())
    charter_path = troupe_dir / "agents" / slug / "charter.md"
    if not charter_path.exists():
        raise AnchorMissingError(
            f"{charter_path.relative_to(root).as_posix()} does not exist — cannot rewrite it"
        )
    old_text = charter_path.read_text(encoding="utf-8")
    new_text = _rewrite_charter_text(old_text, member_name, old_role, new_role)

    return CharterEdit(
        root=root,
        troupe_dir=troupe_dir,
        slug=slug,
        member_name=member_name,
        state=state,
        old_role=old_role,
        new_role=new_role,
        charter_path=charter_path,
        old_charter_text=old_text,
        new_charter_text=new_text,
    )


def _rewrite_charter_text(text: str, name: str, old: Role, new: Role) -> str:
    """Surgically rewrite ONLY the anchors of fields that changed, leaving all
    other prose (including everything below `## Working agreements`) untouched.
    The use hint has no charter.md anchor, so a use-hint-only edit returns the
    text unchanged. Raises AnchorMissingError naming the missing anchor."""
    lines = text.split("\n")
    if new.title != old.title:
        heading_prefix = f"# {name} — "
        _replace_line(lines, heading_prefix, f"# {name} — {new.title}", "heading")
        _replace_line(
            lines, "- **Role:** ", f"- **Role:** {new.title}", "Identity '- **Role:**' line"
        )
    if new.expertise != old.expertise:
        _replace_line(
            lines,
            "- **Expertise:** ",
            f"- **Expertise:** {new.expertise}",
            "Identity '- **Expertise:**' line",
        )
    text = "\n".join(lines)
    if new.ownership != old.ownership:
        # Same technique as scaffold._rewrite_cast_table: replace the section
        # body between the marker and the next "## " heading.
        marker = "## Ownership"
        start = text.find(marker)
        if start == -1:
            raise AnchorMissingError(
                "charter.md has no '## Ownership' section — nothing was written"
            )
        bullets = "\n".join(f"- {item}" for item in new.ownership)
        body_start = start + len(marker)
        next_section = text.find("\n## ", body_start)
        tail = text[next_section:] if next_section != -1 else ""
        text = text[:body_start] + "\n\n" + bullets + "\n" + tail
    return text


def _replace_line(lines: list[str], prefix: str, replacement: str, label: str) -> None:
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = replacement
            return
    raise AnchorMissingError(f"charter.md has no {label} — nothing was written")


def apply_edit(edit: CharterEdit, *, reason: str | None, from_proposal: bool = False) -> None:
    """Apply a prepared edit to all four surfaces, then log a decision entry.

    1. casting-state's `charter` record (the system of record) via
       backup_and_write.
    2. charter.md's changed anchors via backup_and_write (skipped when the
       edit doesn't touch charter.md, e.g. a use-hint-only change).
    3. `.claude/agents/{slug}.md` re-rendered via render_agent_definition —
       keeps the description frontmatter (the enriched-roster source) true.
    4. team.md's Cast row, when the title changed.
    5. A `.troupe/decisions.md` entry attributed to `troupe charter (CLI)`."""
    record = edit.state["assignments"][edit.slug]
    record["charter"] = {
        "title": edit.new_role.title,
        "expertise": edit.new_role.expertise,
        "ownership": list(edit.new_role.ownership),
        "use_hint": edit.new_role.use_hint,
    }
    backup_and_write(
        edit.troupe_dir / "casting-state.json", json.dumps(edit.state, indent=2) + "\n"
    )

    if edit.new_charter_text != edit.old_charter_text:
        backup_and_write(edit.charter_path, edit.new_charter_text)

    member = CastMember(
        entry=PoolEntry(name=edit.member_name, craft=record.get("craft", ""), affinities=()),
        role=record["role"],
        charter=edit.new_role,
    )
    agent_def = edit.root / ".claude" / "agents" / f"{edit.slug}.md"
    agent_def.parent.mkdir(parents=True, exist_ok=True)
    # created_at="" matches `troupe upgrade`'s rendering exactly, so the next
    # upgrade leaves this file byte-identical (the 0.2.0 persistence contract).
    agent_def.write_text(
        render_agent_definition(member, created_at=""), encoding="utf-8", newline="\n"
    )

    if edit.title_changed:
        _rewrite_cast_table(edit.troupe_dir / "team.md", members_from_state(edit.state))

    changes = _describe_changes(edit.old_role, edit.new_role)
    what = f"Updated {edit.member_name}'s charter: {changes}."
    if from_proposal:
        what += " Applied from a staged proposal (propose-then-approve)."
    why = reason.strip() if reason and reason.strip() else "No reason given (--reason not passed)."
    append_decision_entry(
        edit.troupe_dir,
        date=date.today().isoformat(),
        title=f"Charter change for {edit.member_name} via `troupe charter`",
        by="troupe charter (CLI)",
        what=what,
        why=why,
    )


def _describe_changes(old: Role, new: Role) -> str:
    parts = []
    if new.title != old.title:
        parts.append(f"title '{old.title}' -> '{new.title}'")
    if new.expertise != old.expertise:
        parts.append(f"expertise '{old.expertise}' -> '{new.expertise}'")
    if new.ownership != old.ownership:
        parts.append(
            f"ownership list replaced ({len(old.ownership)} -> {len(new.ownership)} item(s))"
        )
    if new.use_hint != old.use_hint:
        parts.append(f"use hint '{old.use_hint}' -> '{new.use_hint}'")
    return "; ".join(parts) if parts else "no field values changed"


def render_diff(edit: CharterEdit) -> str:
    """Unified diff of the charter.md change (empty when charter.md is
    untouched, e.g. a use-hint-only edit)."""
    if edit.new_charter_text == edit.old_charter_text:
        return ""
    rel = edit.charter_path.relative_to(edit.root).as_posix()
    return "".join(
        difflib.unified_diff(
            edit.old_charter_text.splitlines(keepends=True),
            edit.new_charter_text.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


# ── proposals ────────────────────────────────────────────────────────


def proposal_path(root: Path, slug: str) -> Path:
    """The one choke point every proposal file operation (stage/load/discard/
    list) funnels through. `slug` ultimately comes from the CLI's NAME
    argument (lowercased), which is not roster-validated before some callers
    reach here (`--reject` discards before `prepare_edit` runs) — so a slug
    containing path separators or `..` must be rejected here rather than
    trusted, or it becomes a path-traversal write/read/delete rooted outside
    `.troupe/proposals/` (confirmed: enough `../` segments in NAME reach
    arbitrary paths on disk)."""
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        raise CharterEditError(f"'{slug}' is not a valid cast member slug")
    return root.resolve() / ".troupe" / "proposals" / f"charter-{slug}.json"


def stage_proposal(
    root: Path, slug: str, fields: CharterFields, reason: str | None
) -> tuple[Path, bool]:
    """Write (or overwrite — one pending proposal per member) the staged
    proposal file. Returns (path, whether an earlier proposal was replaced)."""
    path = proposal_path(root, slug)
    replaced = path.exists()
    payload = {
        "slug": slug,
        "fields": fields.to_dict(),
        "reason": reason,
        "stagedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path, replaced


def load_proposal(root: Path, slug: str) -> tuple[CharterFields, str | None]:
    """Read a staged proposal back as (fields, staged reason)."""
    path = proposal_path(root, slug)
    if not path.exists():
        raise NoPendingProposalError(
            f"no pending charter proposal for '{slug}' — stage one first (any "
            "non-interactive `troupe charter` field edit stages, or pass --propose)"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CharterEditError(
            f"proposal file {path.relative_to(root.resolve()).as_posix()} is not valid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise CharterEditError(
            f"proposal file {path.relative_to(root.resolve()).as_posix()} is not a JSON object"
        )
    fields = CharterFields.from_dict(raw.get("fields") or {})
    reason = raw.get("reason")
    return fields, str(reason) if reason is not None else None


def discard_proposal(root: Path, slug: str) -> Path:
    path = proposal_path(root, slug)
    if not path.exists():
        raise NoPendingProposalError(f"no pending charter proposal for '{slug}'")
    path.unlink()
    return path


def pending_proposals(root: Path, slug: str | None = None) -> list[dict]:
    """Summaries of staged proposals (all, or one member's), oldest path first."""
    directory = root.resolve() / ".troupe" / "proposals"
    paths = [proposal_path(root, slug)] if slug else sorted(directory.glob("charter-*.json"))
    entries: list[dict] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        fields = raw.get("fields")
        entries.append(
            {
                "slug": raw.get("slug") or path.stem.removeprefix("charter-"),
                "stagedAt": raw.get("stagedAt", "unknown"),
                "fields": sorted(fields) if isinstance(fields, dict) else [],
                "path": path,
            }
        )
    return entries
