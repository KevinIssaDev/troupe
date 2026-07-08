"""Role catalog: what each role owns and how its charter is seeded."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    expertise: str
    ownership: tuple[str, ...]
    use_hint: str
    emoji: str = "🧵"


ROLE_CATALOG: dict[str, Role] = {
    r.id: r
    for r in (
        Role(
            id="lead",
            title="Lead",
            emoji="🎯",
            expertise="Architecture, technical decisions, code review, scope control",
            ownership=(
                "Architectural direction and cross-cutting design decisions",
                "Code review and quality gates",
                "Keeping scope honest — saying no is part of the job",
                "Growing or retiring the cast — run `troupe cast --add-role <role>` "
                "or `troupe cast --retire <name>` via Bash, never by hand-editing "
                "casting-state.json or writing/deleting charter or agent files directly",
            ),
            use_hint=(
                "design decisions, reviews, anything that spans more than one area, "
                "and growing or retiring the cast"
            ),
        ),
        Role(
            id="backend",
            title="Backend",
            emoji="🔧",
            expertise="APIs, services, data models, business logic",
            ownership=(
                "Server-side code: endpoints, services, background jobs",
                "Data models and their migrations",
                "Contracts between the backend and everyone else",
            ),
            use_hint="API, service, and data-layer work",
        ),
        Role(
            id="frontend",
            title="Frontend",
            emoji="⚛️",
            expertise="UI components, styling, client-side state, accessibility",
            ownership=(
                "UI components and their styling",
                "Client-side state and data fetching",
                "Accessibility and responsive behavior",
            ),
            use_hint="UI, styling, and client-side work",
        ),
        Role(
            id="tester",
            title="Tester",
            emoji="🧪",
            expertise="Test plans, regression coverage, edge cases, breaking things on purpose",
            ownership=(
                "Test plans and test code",
                "Regression coverage for fixed bugs",
                "Hunting the edge cases nobody wants to think about",
            ),
            use_hint="writing tests, reviewing coverage, and probing for failure modes",
        ),
        Role(
            id="security",
            title="Security",
            emoji="🛡️",
            expertise="AuthN/authZ, secrets handling, input validation, dependency risk",
            ownership=(
                "Authentication and authorization flows",
                "Secrets handling and credential hygiene",
                "Input validation and dependency risk",
            ),
            use_hint="security review of auth, secrets, and untrusted input",
        ),
        Role(
            id="devops",
            title="DevOps",
            emoji="🔄",
            expertise="CI/CD pipelines, builds, releases, infrastructure",
            ownership=(
                "CI/CD pipelines and build configuration",
                "Release and deployment mechanics",
                "Infrastructure as code",
            ),
            use_hint="pipeline, build, release, and infrastructure work",
        ),
        Role(
            id="docs",
            title="Docs",
            emoji="📋",
            expertise="READMEs, API documentation, changelogs, developer guides",
            ownership=(
                "README and developer guides",
                "API documentation",
                "Changelogs and release notes",
            ),
            use_hint="writing and reviewing documentation",
        ),
        Role(
            id="data",
            title="Data",
            emoji="📊",
            expertise="Schemas, queries, pipelines, analytics",
            ownership=(
                "Database schemas and query performance",
                "Data pipelines and transformations",
                "Analytics and reporting correctness",
            ),
            use_hint="schema, query, and data-pipeline work",
        ),
        Role(
            id="design",
            title="Design",
            emoji="🎨",
            expertise="Interaction design, visual consistency, UX review",
            ownership=(
                "Interaction patterns and visual consistency",
                "UX review of user-facing changes",
                "Design tokens and component guidelines",
            ),
            use_hint="UX and visual-design review",
        ),
    )
}


def resolve_role(role_id: str) -> Role:
    """Look up a catalog role, or synthesize a generic one for unknown ids."""
    known = ROLE_CATALOG.get(role_id)
    if known is not None:
        return known
    title = role_id.replace("-", " ").replace("_", " ").title()
    return Role(
        id=role_id,
        title=title,
        expertise=f"{title} work for this project",
        ownership=(f"{title} tasks and their quality",),
        use_hint=f"{title.lower()} work",
    )
