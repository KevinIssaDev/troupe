"""`troupe upgrade` — refresh troupe-owned files without touching team state."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from troupe.upgrade import NotATroupeProjectError
from troupe.upgrade import upgrade as run_upgrade

PathArg = Annotated[
    Path, typer.Argument(help="Project root to upgrade (defaults to the current directory).")
]


def upgrade(path: PathArg = Path()) -> None:
    """Update hook scripts and agent definitions to the installed troupe
    version, and add any missing policy sections. Team state (charters,
    histories, decisions, directives, casting) is never touched."""
    try:
        result = run_upgrade(path)
    except NotATroupeProjectError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for path_ in result.refreshed:
        typer.echo(f"refreshed {path_.relative_to(result.root)}")
    for path_ in result.extended:
        typer.echo(f"extended  {path_.relative_to(result.root)}")
    if not result.refreshed and not result.extended:
        typer.echo("Everything already current.")
    else:
        typer.echo(
            f"\n{len(result.refreshed)} refreshed, {len(result.extended)} extended, "
            f"{len(result.unchanged)} already current."
        )
