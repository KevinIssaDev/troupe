"""`troupe charter` — edit a cast member's mandate through structured fields.

Fully ungated, same trust model as `troupe cast`: a human is present in any
interactive session and watches the command before it runs, and Claude
Code's own Bash permission prompt is the real backstop — not a custom
staging/approve mechanism (decisions.md 2026-07-08, superseding the phase-1
propose/stage/--approve gate design). A field edit is validated via
`prepare_edit`, then applied immediately and unconditionally.

Exit codes follow the house convention: 0 success, 1 operational failure
(unknown/retired member, missing anchor), 2 usage error (no field flags).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from troupe.charters.editor import (
    CharterEdit,
    CharterEditError,
    CharterFields,
    apply_edit,
    prepare_edit,
)

NameArg = Annotated[str, typer.Argument(help="Cast member name (case-insensitive).")]
PathArg = Annotated[
    Path, typer.Argument(help="Project root to modify (defaults to the current directory).")
]
TitleOpt = Annotated[
    str | None, typer.Option("--title", help="Replace the role title.", show_default=False)
]
ExpertiseOpt = Annotated[
    str | None,
    typer.Option("--expertise", help="Replace the one-line expertise.", show_default=False),
]
OwnershipOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--ownership",
        help=(
            "Ownership bullet (repeatable). All occurrences together REPLACE "
            "the full ownership list — this never appends."
        ),
        show_default=False,
    ),
]
UseHintOpt = Annotated[
    str | None,
    typer.Option("--use-hint", help="Replace the 'Use for ...' hint.", show_default=False),
]
ReasonOpt = Annotated[
    str | None,
    typer.Option("--reason", help="Free text folded into the auto-logged decision entry."),
]


def charter(
    name: NameArg,
    path: PathArg = Path(),
    title: TitleOpt = None,
    expertise: ExpertiseOpt = None,
    ownership: OwnershipOpt = None,
    use_hint: UseHintOpt = None,
    reason: ReasonOpt = None,
) -> None:
    """Edit a cast member's charter: structured fields, applied immediately."""
    fields = CharterFields(
        title=title,
        expertise=expertise,
        ownership=tuple(ownership) if ownership else None,
        use_hint=use_hint,
    )
    if not fields.provided():
        typer.echo(
            "Nothing to change - pass at least one of --title/--expertise/--ownership/--use-hint.",
            err=True,
        )
        raise typer.Exit(code=2)

    root = path.resolve()
    try:
        edit = prepare_edit(root, name, fields)
        if not edit.changed:
            typer.echo("Charter already matches the requested values - nothing to change.")
            return
        apply_edit(edit, reason=reason)
    except CharterEditError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _echo_applied(edit)


def _echo_applied(edit: CharterEdit) -> None:
    typer.echo(f"Updated {edit.member_name}'s charter.")
    typer.echo(
        "Wrote: casting-state.json, "
        f".troupe/agents/{edit.slug}/charter.md, .claude/agents/{edit.slug}.md"
        + (", team.md" if edit.title_changed else "")
        + ", decisions.md."
    )
