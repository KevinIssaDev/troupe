"""Troupe CLI entry point.

Subcommands (init, doctor, upgrade, watch, cast, charter) register on `app`
as they are implemented in `troupe.commands`.
"""

from __future__ import annotations

import typer

from troupe import __version__
from troupe.commands.cast import cast
from troupe.commands.charter import charter
from troupe.commands.doctor import doctor
from troupe.commands.init import init
from troupe.commands.upgrade import upgrade
from troupe.commands.watch import watch

app = typer.Typer(
    name="troupe",
    help="A persistent, governed AI team for Claude Code.",
    no_args_is_help=True,
    add_completion=False,
)

app.command()(init)
app.command()(doctor)
app.command()(upgrade)
app.command()(watch)
app.command()(cast)
app.command()(charter)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"troupe {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the troupe version and exit.",
    ),
) -> None:
    """A persistent, governed AI team for Claude Code."""


def main() -> None:
    app()
