"""Casting policy: `propose_plan(profile, requested_roles) -> CastingPlan`.

Pure policy, no I/O — the roster rule table and the charter-specialization
templates live here so the casting logic is reviewable in one place.
All prose is troupe-authored; repo-derived values interpolate only through
the profile's already-sanitized fields (see discovery/profile.py).

Rule table (v1, signed off 2026-07-06 — see .troupe/decisions.md):
  lead      always
  tester    always (rationale flags a missing suite)
  backend   any real codebase; charter text/title specialize per kind
  frontend  only on frontend evidence (framework dep, or index.html + JS/TS)
  devops    Dockerfile/terraform/k8s markers, or >= 2 CI workflows
  data      migrations dir, ORM dep, or SQL corpus
  docs      a docs *site* (mkdocs/sphinx/docusaurus/populated docs/)
  security  never auto-cast; suggested when auth deps are detected
Roster capped at ROSTER_CAP; drops listed. Never proposes non-catalog ids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from troupe.casting.roles import ROLE_CATALOG, Role, resolve_role
from troupe.discovery.profile import ProjectProfile

ROSTER_CAP = 5
_PRIORITY = ("lead", "backend", "tester", "frontend", "devops", "data", "docs")

# Display names for CLI frameworks we are willing to name in charter prose.
_CLI_FRAMEWORK_DISPLAY = {"typer": "Typer", "click": "Click"}


@dataclass(frozen=True)
class RoleProposal:
    role: Role  # possibly specialized (title, expertise, ownership, use_hint)
    rationale: str  # one line, cites evidence


@dataclass(frozen=True)
class CastingPlan:
    profile: ProjectProfile
    proposals: tuple[RoleProposal, ...]
    dropped: tuple[str, ...]  # role ids that hit the roster cap
    suggestions: tuple[str, ...]  # footer lines, e.g. the security hint


def propose_plan(
    profile: ProjectProfile, requested_roles: Sequence[str] | None = None
) -> CastingPlan:
    """Draft a casting plan from a scanned profile.

    With `requested_roles` (the `--roles` path) the roster is exactly what was
    asked for — no rules, no cap, no suggestions — but each catalog role is
    still specialized to the detected stack so seeding stays tailored.
    """
    if requested_roles is not None:
        proposals = tuple(
            RoleProposal(
                role=_specialize(resolve_role(role_id), profile),
                rationale="requested via --roles",
            )
            for role_id in requested_roles
        )
        return CastingPlan(profile=profile, proposals=proposals, dropped=(), suggestions=())

    candidates: list[RoleProposal] = [
        RoleProposal(ROLE_CATALOG["lead"], "always cast: architecture, review, scope")
    ]
    if _has_code(profile):
        candidates.append(
            RoleProposal(_specialize(ROLE_CATALOG["backend"], profile), _backend_rationale(profile))
        )
    candidates.append(
        RoleProposal(_specialize(ROLE_CATALOG["tester"], profile), _tester_rationale(profile))
    )
    if _wants_frontend(profile):
        candidates.append(RoleProposal(ROLE_CATALOG["frontend"], _frontend_rationale(profile)))
    if _wants_devops(profile):
        candidates.append(
            RoleProposal(_specialize(ROLE_CATALOG["devops"], profile), _devops_rationale(profile))
        )
    if profile.has("data"):
        signal = profile.signals_of("data")[0]
        candidates.append(
            RoleProposal(ROLE_CATALOG["data"], f"{signal.value} detected ({signal.evidence})")
        )
    if profile.has("docs-site"):
        signal = profile.signals_of("docs-site")[0]
        candidates.append(RoleProposal(ROLE_CATALOG["docs"], f"docs site ({signal.evidence})"))

    priority = {role_id: index for index, role_id in enumerate(_PRIORITY)}
    candidates.sort(key=lambda proposal: priority[proposal.role.id])
    proposals = tuple(candidates[:ROSTER_CAP])
    dropped = tuple(proposal.role.id for proposal in candidates[ROSTER_CAP:])

    suggestions: list[str] = []
    if not any(proposal.role.id == "frontend" for proposal in candidates):
        suggestions.append("Not cast: frontend (no frontend markers found).")
    auth = profile.first_signal("auth-dep")
    if auth is not None:
        suggestions.append(
            f"Auth dependency detected ({auth.value} in {auth.evidence}) — consider adding "
            "a security member: --roles ...,security."
        )
    return CastingPlan(
        profile=profile, proposals=proposals, dropped=dropped, suggestions=tuple(suggestions)
    )


# ── rule predicates ──────────────────────────────────────────────────


def _has_code(profile: ProjectProfile) -> bool:
    """False only for trees with no recognized source files and no manifest
    (e.g. a pure-static site or an empty repo)."""
    return bool(profile.languages) or profile.has("manifest")


def _wants_frontend(profile: ProjectProfile) -> bool:
    if profile.has("frontend-framework"):
        return True
    markers = {signal.value for signal in profile.signals_of("frontend-marker")}
    client_tree = bool(markers - {"index.html"}) or any(
        language in ("javascript", "typescript") for language in profile.languages
    )
    return "index.html" in markers and client_tree


def _wants_devops(profile: ProjectProfile) -> bool:
    return profile.has("infra") or len(profile.signals_of("ci-workflow")) >= 2


# ── rationales (troupe-authored; sanitized tokens interpolate) ───────


def _backend_rationale(profile: ProjectProfile) -> str:
    cli = profile.first_signal("cli-entrypoint")
    service = profile.first_signal("service-framework")
    if profile.kind == "cli":
        if cli is not None:
            return f"core CLI logic ({cli.value} entrypoint in {cli.evidence})"
        return "core CLI logic"
    if profile.kind == "library":
        manifest = profile.first_signal("manifest")
        return f"core library logic ({manifest.evidence})" if manifest else "core library logic"
    if service is not None:
        return f"service code ({service.value} in {service.evidence})"
    if profile.languages:
        return f"owns core logic ({profile.languages[0]} codebase)"
    return "owns core logic"


def _tester_rationale(profile: ProjectProfile) -> str:
    framework = profile.first_signal("test-framework")
    tests_dir = profile.first_signal("tests-dir")
    if framework is not None and tests_dir is not None:
        return f"{framework.value} suite in {tests_dir.evidence}"
    if framework is not None:
        return f"{framework.value} configured in {framework.evidence}"
    if tests_dir is not None:
        return f"tests in {tests_dir.evidence}"
    return "no tests detected — first job is building the suite"


def _frontend_rationale(profile: ProjectProfile) -> str:
    signal = profile.first_signal("frontend-framework") or profile.first_signal("frontend-marker")
    if signal is None:  # unreachable when the rule fired; belt and braces
        return "frontend markers found"
    return f"{signal.value} in {signal.evidence}"


def _devops_rationale(profile: ProjectProfile) -> str:
    parts: list[str] = []
    workflows = profile.signals_of("ci-workflow")
    if workflows:
        system = workflows[0].value
        count = sum(1 for signal in workflows if signal.value == system)
        if count > 1:
            parts.append(f"{count} {system} workflows")
        else:
            parts.append(f"{system} ({workflows[0].evidence})")
    infra = profile.first_signal("infra")
    if infra is not None:
        parts.append(f"{infra.value} ({infra.evidence})")
    return ", ".join(parts)


# ── charter specialization templates ─────────────────────────────────


def _specialize(role: Role, profile: ProjectProfile) -> Role:
    """Specialize catalog role text for the detected stack.

    A bounded set of parametrized string templates — deterministic, no
    freeform generation. Returns the catalog role unchanged when no template
    applies; the role *id* is never changed (ids are the stable vocabulary
    for --roles, name affinities, and state records; titles are presentation).
    """
    if role.id == "backend" and profile.kind in ("cli", "library"):
        return _core_role(profile)
    if role.id == "tester":
        return _specialized_tester(role, profile)
    if role.id == "devops":
        return _specialized_devops(role, profile)
    return role


def _core_role(profile: ProjectProfile) -> Role:
    cli = profile.first_signal("cli-entrypoint")
    framework = _CLI_FRAMEWORK_DISPLAY.get(cli.value, "") if cli is not None else ""
    if profile.kind == "cli":
        surface = f"{framework} command surface" if framework else "command surface"
        return Role(
            id="backend",
            title="Core",
            expertise=f"Core CLI logic, {surface}, data models, packaging",
            ownership=(
                "Core command logic and the CLI surface: arguments, exit codes, output contracts",
                "Data models and internal APIs",
                "Contracts between the core and everything else",
            ),
            use_hint="core logic, CLI surface, and data-layer work",
        )
    return Role(
        id="backend",
        title="Core",
        expertise="Core library logic, public API surface, data models, packaging",
        ownership=(
            "Core library logic and the public API surface",
            "Data models and internal APIs",
            "Contracts between the core and everything else",
        ),
        use_hint="core logic, public API, and data-layer work",
    )


def _specialized_tester(role: Role, profile: ProjectProfile) -> Role:
    framework = profile.first_signal("test-framework")
    if framework is None:
        return role
    tests_dir = profile.first_signal("tests-dir")
    suite = f"The {tests_dir.evidence} suite" if tests_dir else f"The {framework.value} suite"
    return replace(
        role,
        expertise=(
            f"Test plans, regression coverage, edge cases — {framework.value} as the "
            "primary harness"
        ),
        ownership=(f"{suite}: structure, fixtures, and coverage", *role.ownership[1:]),
    )


def _specialized_devops(role: Role, profile: ProjectProfile) -> Role:
    workflows = profile.signals_of("ci-workflow")
    if not workflows:
        return role
    if any(signal.value == "GitHub Actions" for signal in workflows):
        pipelines = "CI/CD pipelines in .github/workflows/ and build configuration"
    else:
        pipelines = f"CI/CD pipelines ({workflows[0].evidence}) and build configuration"
    return replace(role, ownership=(pipelines, *role.ownership[1:]))
