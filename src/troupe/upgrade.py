"""`troupe upgrade` core — refresh troupe-owned artifacts, never team state.

Troupe-owned (refreshed to current templates):
  .claude/hooks/*.py           — emitted governance scripts
  .claude/agents/{slug}.md     — compiled agent definitions (customize the
                                 charter, not these; the definition tells the
                                 agent to read its charter first)

Extended, never modified:
  .troupe/policy.json          — missing top-level keys are added with
                                 defaults; existing keys are left exactly
                                 as the user set them
  .claude/settings.json        — missing troupe hook entries are merged in

Never touched: team.md, decisions.md, directives.md, charters, histories,
casting-state.json, config.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from troupe.charters.compiler import render_agent_definition
from troupe.governance.wiring import HOOK_SCRIPTS, merge_hooks_into_settings
from troupe.scaffold import load_state, members_from_state


class NotATroupeProjectError(Exception):
    """Raised when upgrade is run somewhere without a .troupe/ directory."""


@dataclass
class UpgradeResult:
    root: Path
    refreshed: list[Path] = field(default_factory=list)
    extended: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)


def upgrade(root: Path) -> UpgradeResult:
    root = root.resolve()
    troupe_dir = root / ".troupe"
    if not troupe_dir.is_dir():
        raise NotATroupeProjectError(f"No .troupe/ directory in {root} — run `troupe init` first.")
    result = UpgradeResult(root=root)

    for script in HOOK_SCRIPTS:
        desired = files("troupe.templates").joinpath(f"hooks/{script}").read_text(encoding="utf-8")
        _refresh(root / ".claude" / "hooks" / script, desired, result)

    for member in members_from_state(load_state(troupe_dir)):
        desired = render_agent_definition(member, created_at="")
        _refresh(root / ".claude" / "agents" / f"{member.slug}.md", desired, result)

    _extend_policy(troupe_dir / "policy.json", result)
    _rewire_settings(root / ".claude" / "settings.json", result)

    return result


def _refresh(path: Path, desired: str, result: UpgradeResult) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == desired:
        result.unchanged.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desired, encoding="utf-8", newline="\n")
    result.refreshed.append(path)


def _extend_policy(path: Path, result: UpgradeResult) -> None:
    """Add top-level keys that current defaults have and the project's policy
    lacks. Existing keys — including protectedPaths the user trimmed — are
    the user's to own and are never modified."""
    defaults = json.loads(
        files("troupe.templates").joinpath("policy.json").read_text(encoding="utf-8")
    )
    if not path.exists():
        path.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8", newline="\n")
        result.refreshed.append(path)
        return
    policy = json.loads(path.read_text(encoding="utf-8"))
    missing = {key: value for key, value in defaults.items() if key not in policy}
    if not missing:
        result.unchanged.append(path)
        return
    policy.update(missing)
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8", newline="\n")
    result.extended.append(path)


def _rewire_settings(path: Path, result: UpgradeResult) -> None:
    settings: dict = {}
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
    if not merge_hooks_into_settings(settings):
        result.unchanged.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
    result.extended.append(path)
