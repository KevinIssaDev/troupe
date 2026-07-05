"""`troupe init` — scaffold a persistent AI cast in the current repository."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from troupe.casting.registry import CastExhaustedError
from troupe.casting.roles import resolve_role
from troupe.scaffold import DEFAULT_ROLES, scaffold

_DEFAULT_ROLES_CSV = ",".join(DEFAULT_ROLES)

PathArg = Annotated[
    Path,
    typer.Argument(help="Project root to scaffold into (defaults to the current directory)."),
]
RolesOpt = Annotated[
    str,
    typer.Option(
        "--roles",
        help="Comma-separated roles to cast (e.g. lead,backend,frontend,tester,security).",
    ),
]


def init(
    path: PathArg = Path(),
    roles: RolesOpt = _DEFAULT_ROLES_CSV,
) -> None:
    """Scaffold .troupe/ team state and .claude/ agent definitions.

    Idempotent: re-running fills in missing files and casts newly requested
    roles, but never overwrites existing team state or renames a cast member.
    """
    role_list = [r.strip().lower() for r in roles.split(",") if r.strip()]
    if not role_list:
        typer.echo("No roles requested - nothing to do.", err=True)
        raise typer.Exit(code=2)

    try:
        result = scaffold(path, role_list)
    except CastExhaustedError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.cast_added:
        typer.echo("Cast:")
        for member in result.cast_added:
            role = resolve_role(member.role)
            typer.echo(f"  {member.name:<10} {role.title}")
    if result.cast_existing:
        names = ", ".join(m.name for m in result.cast_existing)
        typer.echo(f"Already on the roster: {names}")

    typer.echo(f"Created {len(result.created)} file(s), left {len(result.skipped)} untouched.")
    if result.updated:
        for path in result.updated:
            typer.echo(f"Updated {path.relative_to(result.root)} (troupe hooks wired in).")
    troupe_dir = result.root / ".troupe"
    typer.echo(f"Team state: {troupe_dir}")
    typer.echo("Next: commit .troupe/ and .claude/ so the team travels with the repo.")
