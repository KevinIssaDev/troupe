"""`troupe cast` — grow or retire the cast after `troupe init`.

`--add-role` is a direct pass-through to `scaffold()`'s existing multiset
gap-fill (docs/design/cast-recast-retire.md) — zero new casting logic.
`--retire` is new: archives a member in casting-state.json (status ->
"retired", `retiredAt` set) and deletes their compiled
`.claude/agents/{slug}.md`; `charter.md`/`history.md` are never touched.
Retires are applied before adds, so one invocation reads as one atomic
roster change and logs exactly one `.troupe/decisions.md` entry. Every
input here is explicit (a role id, a cast member's name), so — unlike
scan-aware init's auto-proposed roster — there is no confirm prompt and no
`--dry-run`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from troupe.casting.registry import CastExhaustedError, CastMember
from troupe.scaffold import log_recast_decision, retire_members, scaffold

PathArg = Annotated[
    Path, typer.Argument(help="Project root to modify (defaults to the current directory).")
]
AddRoleOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--add-role",
        help=(
            "Cast a new member for this role id (repeatable, one role per occurrence). "
            "A no-op if the role is already covered - pass it twice to add a second."
        ),
    ),
]
RetireOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--retire",
        help="Retire an active cast member by name (repeatable, case-insensitive).",
    ),
]
ReasonOpt = Annotated[
    str | None,
    typer.Option("--reason", help="Free text folded into the auto-logged decision entry."),
]


def cast(
    path: PathArg = Path(),
    add_role: AddRoleOpt = None,
    retire: RetireOpt = None,
    reason: ReasonOpt = None,
) -> None:
    """Grow or retire the cast: `--add-role <role>` and/or `--retire <name>`."""
    add_roles = add_role or []
    retire_names = retire or []
    if not add_roles and not retire_names:
        typer.echo("Nothing to add or retire - pass --add-role or --retire.", err=True)
        raise typer.Exit(code=2)

    root = path.resolve()
    troupe_dir = root / ".troupe"

    retired: list[CastMember] = []
    not_found: list[str] = []
    already_retired: list[str] = []
    warnings: list[str] = []
    if retire_names:
        retire_result = retire_members(path, retire_names)
        retired = retire_result.retired
        not_found = retire_result.not_found
        already_retired = retire_result.already_retired
        warnings = retire_result.warnings

    added: list[CastMember] = []
    if add_roles:
        try:
            scaffold_result = scaffold(path, roles=add_roles)
        except CastExhaustedError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        added = scaffold_result.cast_added

    log_recast_decision(troupe_dir, retired, added, reason)

    if retired:
        typer.echo("Retired:")
        for member in retired:
            typer.echo(f"  {member.name:<10} {member.role}")
    if added:
        typer.echo("Cast:")
        for member in added:
            typer.echo(f"  {member.name:<10} {member.effective_role().title}")
    if not retired and not added:
        typer.echo("Nothing changed.")

    for warning in warnings:
        typer.echo(f"Warning: {warning}.")
    for name in not_found:
        typer.echo(f"error: no active cast member named '{name}'", err=True)
    for name in already_retired:
        typer.echo(f"error: '{name}' is already retired", err=True)

    if not_found or already_retired:
        raise typer.Exit(code=1)
