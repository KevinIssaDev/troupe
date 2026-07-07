"""`troupe charter` — edit a cast member's mandate through structured fields.

The human gate: on a TTY the command previews a unified diff of the
charter.md change and asks for confirmation (there is deliberately no
`--yes`); off a TTY — i.e. any agent Bash call — field edits never apply.
They stage a proposal at `.troupe/proposals/charter-{slug}.json` and print
the `troupe charter NAME --approve` handoff for the human's own terminal.
`--approve` re-renders the diff from the proposal file at approve time (so
a proposal edited after staging is what the human actually reviews),
requires a TTY, applies, and deletes the proposal.

`--approve-all` applies every pending proposal in one batch: same TTY-only,
no-bypass gate as `--approve`, and mutually exclusive with NAME (it always
operates on all pending proposals under PATH). All proposals are validated
before anything is written — one bad proposal (unknown/retired member,
missing anchor, or a tampered embedded slug) aborts the whole batch. A
no-op proposal is dropped from the apply set and discarded, called out
separately in the summary. On confirm, every applied and no-op proposal is
discarded and ONE combined decision entry is logged for the batch.

Exit codes follow the house convention: 0 success (including a declined
confirm), 1 operational failure (unknown/retired member, missing anchor,
nothing pending), 2 usage error (no field flags, conflicting flags,
--approve off a TTY).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from troupe.charters.editor import (
    CharterEdit,
    CharterEditError,
    CharterFields,
    NoPendingProposalError,
    apply_charter_surfaces,
    apply_edit,
    discard_proposal,
    load_proposal,
    log_batch_decision,
    pending_proposals,
    prepare_batch,
    prepare_edit,
    render_diff,
    stage_proposal,
)

NameArg = Annotated[
    str | None,
    typer.Argument(
        help="Cast member name (case-insensitive). Optional only with --list.", show_default=False
    ),
]
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
ProposeOpt = Annotated[
    bool,
    typer.Option(
        "--propose",
        help="Stage the edit as a proposal instead of applying (implied off a TTY).",
    ),
]
ApproveOpt = Annotated[
    bool,
    typer.Option(
        "--approve",
        help="Apply the staged proposal for NAME (requires a human terminal; no bypass).",
    ),
]
RejectOpt = Annotated[bool, typer.Option("--reject", help="Discard the staged proposal for NAME.")]
ListOpt = Annotated[
    bool, typer.Option("--list", help="List pending charter proposals (NAME optional).")
]
ApproveAllOpt = Annotated[
    bool,
    typer.Option(
        "--approve-all",
        help=(
            "Apply every pending charter proposal in one batch (requires a human "
            "terminal; no bypass). Mutually exclusive with NAME."
        ),
    ),
]


def charter(
    name: NameArg = None,
    path: PathArg = Path(),
    title: TitleOpt = None,
    expertise: ExpertiseOpt = None,
    ownership: OwnershipOpt = None,
    use_hint: UseHintOpt = None,
    reason: ReasonOpt = None,
    propose: ProposeOpt = False,
    approve: ApproveOpt = False,
    reject: RejectOpt = False,
    list_pending: ListOpt = False,
    approve_all: ApproveAllOpt = False,
) -> None:
    """Edit a cast member's charter: structured fields, human-gated apply."""
    fields = CharterFields(
        title=title,
        expertise=expertise,
        ownership=tuple(ownership) if ownership else None,
        use_hint=use_hint,
    )
    root = path.resolve()

    modes = [
        flag
        for flag, on in (
            ("--approve", approve),
            ("--reject", reject),
            ("--list", list_pending),
            ("--approve-all", approve_all),
        )
        if on
    ]
    if len(modes) > 1:
        typer.echo(f"Pass only one of {', '.join(modes)}.", err=True)
        raise typer.Exit(code=2)
    if modes and (fields.provided() or propose):
        typer.echo(f"{modes[0]} cannot be combined with field flags or --propose.", err=True)
        raise typer.Exit(code=2)
    if approve_all and name is not None:
        typer.echo("--approve-all cannot be combined with NAME.", err=True)
        raise typer.Exit(code=2)

    try:
        if approve_all:
            _approve_all(root, reason)
            return
        if list_pending:
            _list(root, name)
            return
        if name is None:
            typer.echo("Missing cast member name - `troupe charter NAME ...`.", err=True)
            raise typer.Exit(code=2)
        slug = name.strip().lower()
        if approve:
            _approve(root, name, slug, reason)
            return
        if reject:
            discarded = discard_proposal(root, slug)
            typer.echo(f"Discarded proposal {discarded.relative_to(root).as_posix()}.")
            return
        if not fields.provided():
            typer.echo(
                "Nothing to change - pass at least one of --title/--expertise/"
                "--ownership/--use-hint (or --approve/--reject/--list).",
                err=True,
            )
            raise typer.Exit(code=2)

        edit = prepare_edit(root, name, fields)
        if not edit.changed:
            typer.echo("Charter already matches the requested values - nothing to change.")
            return
        if propose or not sys.stdin.isatty():
            _stage(root, path, slug, fields, reason, forced=propose)
            return
        _confirm_and_apply(edit, reason=reason, from_proposal=False)
        _echo_applied(edit)
    except CharterEditError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ── flows ────────────────────────────────────────────────────────────


def _stage(
    root: Path, path_arg: Path, slug: str, fields: CharterFields, reason: str | None, forced: bool
) -> None:
    # The caller has already run prepare_edit, so an unknown/retired member
    # or a missing anchor fails now (exit 1), never at the human's approve.
    proposal, replaced = stage_proposal(root, slug, fields, reason)
    rel = proposal.relative_to(root).as_posix()
    if replaced:
        typer.echo(f"Replaced the previously staged proposal for '{slug}'.")
    typer.echo(f"Staged charter proposal at {rel} - nothing applied yet.")
    if not forced:
        typer.echo("Charter edits from a non-interactive session always stage a proposal;")
        typer.echo("the apply is a human terminal action.")
    handoff = f"troupe charter {slug} --approve"
    if path_arg != Path():
        handoff = f"troupe charter {slug} {path_arg} --approve"
    typer.echo(f"A human applies it with: {handoff}")


def _approve(root: Path, name: str, slug: str, reason: str | None) -> None:
    if not sys.stdin.isatty():
        typer.echo(
            "--approve is the human gate - run this in your own terminal, "
            "not from an agent session.",
            err=True,
        )
        raise typer.Exit(code=2)
    fields, staged_reason = load_proposal(root, slug)
    if not fields.provided():
        discard_proposal(root, slug)
        typer.echo("Proposal contained no fields - discarded it; nothing to apply.")
        return
    # The diff below is rendered from the proposal file's content as it is
    # NOW, so anything edited into it after staging is what gets reviewed.
    edit = prepare_edit(root, name, fields)
    if not edit.changed:
        discard_proposal(root, slug)
        typer.echo("Charter already matches the proposal - discarded it; nothing to apply.")
        return
    _confirm_and_apply(
        edit, reason=reason if reason is not None else staged_reason, from_proposal=True
    )
    discard_proposal(root, slug)
    _echo_applied(edit)
    typer.echo("Proposal applied and removed.")


def _approve_all(root: Path, reason: str | None) -> None:
    if not sys.stdin.isatty():
        typer.echo(
            "--approve-all is the human gate - run this in your own terminal, "
            "not from an agent session.",
            err=True,
        )
        raise typer.Exit(code=2)

    batch = prepare_batch(root)
    if not batch.to_apply and not batch.no_op_slugs:
        raise NoPendingProposalError("no pending charter proposals")

    if not batch.to_apply:
        for slug in batch.no_op_slugs:
            discard_proposal(root, slug)
        typer.echo(f"0 to apply, {len(batch.no_op_slugs)} already matched (discarded).")
        return

    to_apply = batch.to_apply
    members = sorted({edit.member_name for edit in to_apply})
    with_diff = sum(1 for edit in to_apply if render_diff(edit))
    summary = f"{len(to_apply)} to apply"
    if batch.no_op_slugs:
        summary += f", {len(batch.no_op_slugs)} already matched (discarded)"
    typer.echo(summary + ".")

    for edit in to_apply:
        typer.echo(f"=== {edit.slug} ===")
        diff = render_diff(edit)
        if diff:
            typer.echo(diff, nl=False)
        else:
            typer.echo("charter.md is unchanged (the use hint is not rendered there).")
    typer.echo("")
    typer.echo(
        "This also recompiles each member's .claude/agents/{slug}.md "
        "(and team.md rows for title changes)."
    )

    try:
        confirmed = typer.confirm(
            f"Apply {with_diff} charter change(s) for {len(to_apply)} member(s)?"
        )
    except typer.Abort:
        _refuse_non_interactive()
    if not confirmed:
        typer.echo("Nothing written. Proposals are kept untouched.")
        raise typer.Exit(code=0)

    for edit in to_apply:
        apply_charter_surfaces(edit)
    log_batch_decision(root / ".troupe", to_apply, reason)
    for edit in to_apply:
        discard_proposal(root, edit.slug)
    for slug in batch.no_op_slugs:
        discard_proposal(root, slug)

    typer.echo(f"Applied charter changes for {len(to_apply)} member(s): {', '.join(members)}.")


def _confirm_and_apply(edit: CharterEdit, *, reason: str | None, from_proposal: bool) -> None:
    diff = render_diff(edit)
    if diff:
        typer.echo(diff, nl=False)
    else:
        typer.echo("charter.md is unchanged (the use hint is not rendered there).")
    typer.echo("")
    surfaces = f"This also recompiles .claude/agents/{edit.slug}.md"
    if edit.title_changed:
        surfaces += " and rewrites the team.md roster row"
    typer.echo(surfaces + ".")
    try:
        confirmed = typer.confirm("Apply this charter change?")
    except typer.Abort:
        _refuse_non_interactive()
    if not confirmed:
        if from_proposal:
            typer.echo("Nothing written. The proposal is kept; discard it with --reject.")
        else:
            typer.echo("Nothing written.")
        raise typer.Exit(code=0)
    apply_edit(edit, reason=reason, from_proposal=from_proposal)


def _refuse_non_interactive() -> NoReturn:
    typer.echo(
        "non-interactive: charter changes apply only from a human terminal "
        "(--propose stages one for later approval)",
        err=True,
    )
    raise typer.Exit(code=2)


def _echo_applied(edit: CharterEdit) -> None:
    typer.echo(f"Updated {edit.member_name}'s charter.")
    typer.echo(
        "Wrote: casting-state.json, "
        f".troupe/agents/{edit.slug}/charter.md, .claude/agents/{edit.slug}.md"
        + (", team.md" if edit.title_changed else "")
        + ", decisions.md."
    )


def _list(root: Path, name: str | None) -> None:
    slug = name.strip().lower() if name else None
    entries = pending_proposals(root, slug)
    if not entries:
        typer.echo("No pending charter proposals.")
        return
    typer.echo("Pending charter proposals:")
    for entry in entries:
        fields_desc = ", ".join(entry["fields"]) if entry["fields"] else "(no fields)"
        typer.echo(f"  {entry['slug']:<10} staged {entry['stagedAt']}  fields: {fields_desc}")
        typer.echo(f"             apply with: troupe charter {entry['slug']} --approve")
