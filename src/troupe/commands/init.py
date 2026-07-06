"""`troupe init` — scan the repository, propose a tailored cast, confirm, scaffold.

Flow (docs/design/scan-aware-init.md, signed off 2026-07-06):
  scan (deterministic, offline) -> propose (rule table + specialization) ->
  confirm (TTY prompt / --yes / --dry-run; non-TTY without --yes/--roles
  exits 2) -> scaffold. No file is written before confirmation. Explicit
  --roles bypasses the proposal but the scan still tailors seeding;
  --no-scan restores the pre-scan behavior verbatim.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from troupe.casting.registry import CastExhaustedError, CastMember
from troupe.discovery.advisor import ROSTER_CAP, CastingPlan, RoleProposal, propose_plan
from troupe.discovery.profile import ProjectProfile
from troupe.discovery.scanner import scan
from troupe.scaffold import DEFAULT_ROLES, ScaffoldResult, preview_cast, scaffold

PathArg = Annotated[
    Path,
    typer.Argument(help="Project root to scaffold into (defaults to the current directory)."),
]
RolesOpt = Annotated[
    str | None,
    typer.Option(
        "--roles",
        help=(
            "Comma-separated roles to cast (e.g. lead,backend,frontend,tester,security). "
            "Skips the scan proposal and prompt; the scan still tailors charter seeding."
        ),
    ),
]
YesOpt = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Accept the proposed cast without prompting."),
]
DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Print the scan and proposal, then exit without writing."),
]
NoScanOpt = Annotated[
    bool,
    typer.Option(
        "--no-scan",
        help="Skip the repository scan: default (or --roles) roles with generic charters.",
    ),
]

_KIND_LABELS = {
    "cli": "CLI",
    "service": "service",
    "frontend-app": "frontend app",
    "library": "library",
    "mixed": "full-stack app",
    "unknown": "project",
}
_LANGUAGE_LABELS = {
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "rust": "Rust",
    "go": "Go",
    "ruby": "Ruby",
    "java": "Java",
    "kotlin": "Kotlin",
    "csharp": "C#",
    "php": "PHP",
    "swift": "Swift",
    "c": "C",
    "cpp": "C++",
    "shell": "shell",
}


def init(
    path: PathArg = Path(),
    roles: RolesOpt = None,
    yes: YesOpt = False,
    dry_run: DryRunOpt = False,
    no_scan: NoScanOpt = False,
) -> None:
    """Scaffold .troupe/ team state and .claude/ agent definitions.

    Scans the repository first (offline, deterministic, no network) so the
    proposed cast and their charters fit the project, and confirms before
    writing anything. Idempotent: re-running fills in missing files and casts
    newly requested roles, but never overwrites existing team state or renames
    a cast member.
    """
    role_list: list[str] | None = None
    if roles is not None:
        role_list = [r.strip().lower() for r in roles.split(",") if r.strip()]
        if not role_list:
            typer.echo("No roles requested - nothing to do.", err=True)
            raise typer.Exit(code=2)

    plan: CastingPlan | None = None
    if not no_scan:
        plan = propose_plan(scan(path), requested_roles=role_list)

    requested_ids = (
        [proposal.role.id for proposal in plan.proposals]
        if plan is not None
        else (role_list or list(DEFAULT_ROLES))
    )
    try:
        existing, new_members = preview_cast(path, requested_ids)
    except CastExhaustedError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if plan is not None and role_list is None:
        # Auto-proposed roster: nothing is written before confirmation.
        if not new_members:
            typer.echo("Roster already covers the detected stack; nothing new to cast.")
            if dry_run:
                typer.echo("Dry run: nothing written.")
                raise typer.Exit(code=0)
        else:
            _echo_proposal(plan, existing, new_members)
            if dry_run:
                typer.echo("Dry run: nothing written.")
                raise typer.Exit(code=0)
            if not yes:
                if not sys.stdin.isatty():
                    _refuse_non_interactive()
                try:
                    confirmed = typer.confirm("Cast this team?")
                except typer.Abort:
                    # stdin looked like a TTY but the prompt could not read
                    # (EOF / closed stdin): same fail-safe as plain non-TTY.
                    _refuse_non_interactive()
                if not confirmed:
                    typer.echo("Nothing written. Re-run with --roles to pick your own cast.")
                    raise typer.Exit(code=0)
    elif dry_run:
        if plan is not None:
            _echo_proposal(plan, existing, new_members)
        else:
            _echo_roles_preview(existing, new_members)
        typer.echo("Dry run: nothing written.")
        raise typer.Exit(code=0)

    try:
        result = scaffold(path, roles=role_list, plan=plan)
    except CastExhaustedError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _echo_result(result)


def _refuse_non_interactive() -> NoReturn:
    typer.echo(
        "non-interactive: pass --yes to accept this cast or --roles to choose",
        err=True,
    )
    raise typer.Exit(code=2)


# ── output helpers ───────────────────────────────────────────────────


def _echo_proposal(
    plan: CastingPlan, existing: list[CastMember], new_members: list[CastMember]
) -> None:
    profile = plan.profile
    header = f"Project: {profile.name}"
    if profile.description:
        header += f' — "{profile.description}"'
    typer.echo(header)
    typer.echo(f"Detected: {_detected_summary(profile)}")
    typer.echo("")

    new_pairs = [
        (member, proposal)
        for member, proposal, is_new in _pair_members(plan.proposals, existing, new_members)
        if is_new
    ]
    if new_pairs:
        typer.echo("Proposed cast:")
        for member, proposal in new_pairs:
            typer.echo(f"  {member.name:<10} {proposal.role.title:<9} {proposal.rationale}")
    if existing:
        typer.echo("Already on the roster: " + ", ".join(m.name for m in existing))
    typer.echo("")
    for line in plan.suggestions:
        typer.echo(line)
    if plan.dropped:
        typer.echo(
            f"Not cast (roster cap of {ROSTER_CAP}): "
            + ", ".join(plan.dropped)
            + " — add with --roles if needed."
        )


def _pair_members(
    proposals: tuple[RoleProposal, ...],
    existing: list[CastMember],
    new_members: list[CastMember],
) -> list[tuple[CastMember, RoleProposal, bool]]:
    """Align each proposal with the member (existing or newly allocated) who
    fills it, mirroring the multiset logic in scaffold."""
    by_role: dict[str, list[CastMember]] = {}
    for member in existing:
        by_role.setdefault(member.role, []).append(member)
    new_iter = iter(new_members)
    pairs: list[tuple[CastMember, RoleProposal, bool]] = []
    for proposal in proposals:
        bucket = by_role.get(proposal.role.id)
        if bucket:
            pairs.append((bucket.pop(0), proposal, False))
        else:
            pairs.append((next(new_iter), proposal, True))
    return pairs


def _detected_summary(profile: ProjectProfile) -> str:
    kind = _KIND_LABELS.get(profile.kind, profile.kind)
    if profile.languages:
        language = _LANGUAGE_LABELS.get(profile.languages[0], profile.languages[0])
        parts = [f"{language} {kind}"]
    else:
        parts = [kind]
    entrypoint = profile.first_signal("cli-entrypoint")
    if entrypoint is not None:
        parts[0] += f" ({entrypoint.value} entrypoint in {entrypoint.evidence})"

    seen: set[str] = set()
    for signal in profile.signals:
        if signal.kind in ("service-framework", "test-framework") and signal.value not in seen:
            seen.add(signal.value)
            parts.append(signal.value)
    ci_counts: dict[str, int] = {}
    for signal in profile.signals_of("ci-workflow"):
        ci_counts[signal.value] = ci_counts.get(signal.value, 0) + 1
    for system, count in ci_counts.items():
        parts.append(f"{system} ({count} workflow{'s' if count != 1 else ''})")
    for signal in profile.signals:
        if signal.kind in ("infra", "data") and signal.value not in seen:
            seen.add(signal.value)
            parts.append(signal.value)
    if profile.has("docs-site"):
        parts.append("docs site")

    summary = ", ".join(parts) + "."
    absences = []
    if not (profile.has("frontend-framework") or profile.has("frontend-marker")):
        absences.append("No frontend.")
    if not profile.has("docs-site"):
        absences.append("No docs site.")
    return summary + (" " + " ".join(absences) if absences else "")


def _echo_roles_preview(existing: list[CastMember], new_members: list[CastMember]) -> None:
    if new_members:
        typer.echo("Would cast:")
        for member in new_members:
            typer.echo(f"  {member.name:<10} {member.effective_role().title}")
    else:
        typer.echo("Nothing new to cast.")
    if existing:
        typer.echo("Already on the roster: " + ", ".join(m.name for m in existing))


def _echo_result(result: ScaffoldResult) -> None:
    if result.cast_added:
        typer.echo("Cast:")
        for member in result.cast_added:
            typer.echo(f"  {member.name:<10} {member.effective_role().title}")
    if result.cast_existing:
        names = ", ".join(m.name for m in result.cast_existing)
        typer.echo(f"Already on the roster: {names}")

    typer.echo(f"Created {len(result.created)} file(s), left {len(result.skipped)} untouched.")
    for updated in result.updated:
        rel = updated.relative_to(result.root)
        note = " (troupe hooks wired in)" if updated.name == "settings.json" else ""
        typer.echo(f"Updated {rel}{note}.")
    troupe_dir = result.root / ".troupe"
    typer.echo(f"Team state: {troupe_dir}")
    typer.echo("Next: commit .troupe/ and .claude/ so the team travels with the repo.")
    typer.echo("Then: open Claude Code and run /troupe-explore, or tell the team directly.")
