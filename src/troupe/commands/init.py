"""`troupe init` — scaffold .troupe/ team state and .claude/ agent definitions.

Bare `init` (no flags — mirrors `doctor`'s signature: at most a path
argument) unconditionally scaffolds governance with zero cast members:
casting-state.json ships with empty assignments, team.md's `## Cast` table
is empty, and all three command templates plus hooks/settings are wired.
No scan, no proposal, no confirmation prompt — always the same output shape
for a given target directory. Casting a real team is `/troupe-setup`'s job
(a live, repo-grounded Claude Code session), not this command's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from troupe.casting.registry import CastExhaustedError
from troupe.scaffold import ScaffoldResult, scaffold

PathArg = Annotated[
    Path,
    typer.Argument(help="Project root to scaffold into (defaults to the current directory)."),
]


def init(path: PathArg = Path()) -> None:
    """Scaffold .troupe/ team state and .claude/ agent definitions.

    Casts nobody — casting-state.json starts with zero assignments and
    team.md's Cast table is empty. Idempotent: re-running fills in any
    missing files but never overwrites existing team state. Open Claude
    Code and run /troupe-setup afterward to cast a team grounded in a real
    read of the repo.
    """
    try:
        result = scaffold(path, roles=[])
    except CastExhaustedError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _echo_result(result)


def _echo_result(result: ScaffoldResult) -> None:
    typer.echo(f"Created {len(result.created)} file(s), left {len(result.skipped)} untouched.")
    for updated in result.updated:
        rel = updated.relative_to(result.root)
        note = " (troupe hooks wired in)" if updated.name == "settings.json" else ""
        typer.echo(f"Updated {rel}{note}.")
    troupe_dir = result.root / ".troupe"
    typer.echo(f"Team state: {troupe_dir}")
    typer.echo("Next: commit .troupe/ and .claude/ so the team travels with the repo.")
    typer.echo(
        "No cast yet — that's expected. Open Claude Code and run /troupe-setup to cast "
        "your team, grounded in a real read of this repo."
    )
