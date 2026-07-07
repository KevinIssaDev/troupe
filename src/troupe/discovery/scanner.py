"""Deterministic repository scanner: `scan(root) -> ProjectProfile`.

Pure detection, no policy. Bounded and offline: known paths are checked
explicitly, plus one sorted directory walk limited to depth 5 from the root
(skipping vendored/build dirs), capped at 3,000 entries; no file larger than
512 KB is read; no network, no subprocesses. Same tree in, same profile out.

Monorepo-aware (shipped 0.3.0 — see CHANGELOG.md): a directory directly
containing a known manifest filename is a "component root". Every
per-ecosystem/marker scan runs once per discovered component root (the
scanned root itself, plus any nested ones), with evidence paths prefixed by
the component's path relative to the true scan root. Component discovery is
a zero-extra-filesystem-call, in-memory pass over the walk's own output.

Every string extracted from the repo leaves this module through
`sanitize_extracted` (via `_signal()`, the component-evidence prefix step in
`scan()`, or the final ProjectProfile construction) — no consumer can receive
raw repo text. `rel`, a component's raw filesystem-relative path, is used
as-is for actual I/O (`root / rel`, `_scoped_entries`) since it must match
real on-disk bytes, but is never written into a Signal's evidence without
passing through `sanitize_extracted` first.
"""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from collections import Counter
from dataclasses import replace
from pathlib import Path

from troupe.discovery.profile import (
    MAX_DESCRIPTION,
    MAX_EVIDENCE,
    MAX_NAME,
    MAX_VALUE,
    ProjectProfile,
    Signal,
    sanitize_extracted,
)

_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", ".tox"}
)
_MAX_DEPTH = 5
_MAX_ENTRIES = 3000
_MAX_FILE_BYTES = 512 * 1024

# Manifest filenames that mark a directory as a component root (monorepo
# discovery). "requirements*.txt" is handled separately in _has_manifest_at
# since it's a glob, not an exact name.
_MANIFEST_NAMES = ("pyproject.toml", "setup.cfg", "package.json", "Cargo.toml", "go.mod")

# Legibility cap (not a cost control — extra components are nearly free to
# scan, just not free to display).
MAX_COMPONENTS = 12

# Extension census -> canonical language tokens.
_LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".swift": "swift",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".sh": "shell",
}

# Known-vocabulary maps: detected dependency name -> troupe's canonical token.
_SERVICE_FRAMEWORKS = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "express": "express",
    "koa": "koa",
    "fastify": "fastify",
    "actix-web": "actix-web",
    "axum": "axum",
}
_FRONTEND_FRAMEWORKS = {
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "next": "next",
    "@angular/core": "angular",
    "solid-js": "solid",
}
_NODE_TEST_FRAMEWORKS = {"jest": "jest", "vitest": "vitest", "mocha": "mocha"}
_ORM_DEPS = {
    "sqlalchemy": "sqlalchemy",
    "prisma": "prisma",
    "@prisma/client": "prisma",
    "drizzle-orm": "drizzle",
}
_AUTH_DEPS = {
    "passlib",
    "pyjwt",
    "authlib",
    "oauthlib",
    "python-jose",
    "django-allauth",
    "flask-login",
    "bcrypt",
    "argon2-cffi",
    "jsonwebtoken",
    "passport",
    "next-auth",
    "@auth/core",
    "express-session",
}
_CLI_FRAMEWORKS = {"typer": "typer", "click": "click"}

_DEP_NAME_RE = re.compile(r"^\s*([A-Za-z0-9@][A-Za-z0-9._/@-]*)")
_GO_MODULE_RE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
_GO_REQUIRE_RE = re.compile(r"^\s*([\w.-]+(?:/[\w.-]+)+)\s+v", re.MULTILINE)


def scan(root: Path) -> ProjectProfile:
    """Scan a project tree into a ProjectProfile. Deterministic and offline."""
    root = root.resolve()
    entries = _walk(root)
    entry_set = set(entries)
    component_roots, skipped = _discover_components(entry_set)

    signals: list[Signal] = []
    name = ""
    description = ""

    for rel in component_roots:
        component_dir = root if not rel else root / rel
        component_entries = _scoped_entries(entries, rel)
        start = len(signals)

        for ecosystem_scan in (_scan_python, _scan_node, _scan_rust, _scan_go):
            found_name, found_description = ecosystem_scan(component_dir, signals)
            name = name or found_name
            description = description or found_description
        _scan_frontend_markers(component_dir, component_entries, signals)
        _scan_tests(component_dir, component_entries, signals)
        _scan_infra(component_dir, component_entries, signals)
        _scan_data(component_dir, component_entries, signals)

        if rel:  # non-root component: prefix this component's new evidence
            for i in range(start, len(signals)):
                prefixed = f"{rel}/{signals[i].evidence}"
                signals[i] = replace(
                    signals[i], evidence=sanitize_extracted(prefixed, MAX_EVIDENCE)
                )

    _scan_ci(root, signals)  # unchanged: root-only, one CI config covers a whole monorepo
    _scan_docs(root, signals)  # unchanged: root-only, same reasoning

    deduped = _dedupe(signals)
    languages = _language_census(entries)  # unchanged: whole-tree, benefits from a deeper walk
    kind = "monorepo" if len(component_roots) > 1 else _derive_kind(deduped, languages)
    components = tuple(sanitize_extracted(c, MAX_EVIDENCE) for c in component_roots if c)
    return ProjectProfile(
        name=sanitize_extracted(name or root.name, MAX_NAME),
        description=sanitize_extracted(description, MAX_DESCRIPTION),
        kind=kind,
        languages=languages,
        signals=tuple(deduped),
        components=components,
        components_truncated=skipped,
    )


# ── bounded walk ─────────────────────────────────────────────────────


def _walk(root: Path) -> list[str]:
    """Sorted repo-relative POSIX paths (dirs carry a trailing '/'), depth <=
    _MAX_DEPTH, capped at _MAX_ENTRIES."""
    entries: list[str] = []

    def visit(directory: Path, depth: int) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for child in children:
            if len(entries) >= _MAX_ENTRIES:
                return
            rel = child.relative_to(root).as_posix()
            if child.is_dir():
                if child.name in _SKIP_DIRS:
                    continue
                entries.append(rel + "/")
                if depth < _MAX_DEPTH:
                    visit(child, depth + 1)
            else:
                entries.append(rel)

    visit(root, 1)
    return entries


def _has_manifest_at(prefix: str, entry_set: set[str]) -> bool:
    """True if `prefix` (a component-relative dir, "" for the scan root)
    directly contains a known manifest filename. No I/O: pure `entry_set`
    lookups against the walk's already-collected paths."""
    for name in _MANIFEST_NAMES:
        candidate = name if not prefix else f"{prefix}/{name}"
        if candidate in entry_set:
            return True
    req_prefix = f"{prefix}/" if prefix else ""
    for entry in entry_set:
        if entry.endswith("/") or not entry.startswith(req_prefix):
            continue
        remainder = entry[len(req_prefix) :]
        if (
            "/" not in remainder
            and remainder.startswith("requirements")
            and remainder.endswith(".txt")
        ):
            return True
    return False


def _discover_components(entry_set: set[str]) -> tuple[list[str], int]:
    """Find every directory that is a "component root" — one that directly
    contains a known manifest filename. Returns (component roots, count
    skipped past MAX_COMPONENTS).

    "" denotes the scanned root itself. Once a directory qualifies as a
    component, nothing nested further inside it is considered for a
    *further* component: a manifest nested inside another component's own
    directory is far more often vendored/example/fixture content than a
    legitimate independent sub-package, and treating every nested manifest
    as its own component would produce phantom components and spurious
    casting signals more often than it would correctly surface a real
    nested package (accepted tradeoff, see .troupe/decisions.md — revisit
    only on real-world evidence otherwise).

    `sorted()` over paths is safe for parent-before-child ordering: a
    directory's own relative path is always a literal string prefix of its
    descendants', and a shorter string that is a prefix of a longer one
    always sorts first lexicographically.
    """
    roots: list[str] = []
    skipped = 0
    if _has_manifest_at("", entry_set):
        roots.append("")
    for entry in sorted(entry_set):
        if not entry.endswith("/"):
            continue
        rel = entry[:-1]
        if any(rel == r or rel.startswith(r + "/") for r in roots if r):
            continue  # nested inside an already-claimed component
        if not _has_manifest_at(rel, entry_set):
            continue
        if len(roots) >= MAX_COMPONENTS:
            skipped += 1
            continue
        roots.append(rel)
    return roots, skipped


def _scoped_entries(entries: list[str], rel: str) -> list[str]:
    """Re-relativize the whole-tree `entries` list under a component prefix
    so the marker-scan functions receive root-relative paths regardless of
    whether "root" is the true scan root or a nested component directory."""
    if not rel:
        return entries
    prefix = f"{rel}/"
    return [entry[len(prefix) :] for entry in entries if entry.startswith(prefix)]


def _read_text(path: Path) -> str | None:
    """Read a file if it exists and is under the size cap; None otherwise.

    utf-8-sig: identical to utf-8 except a leading BOM is stripped — Windows
    tools (PowerShell 5.1, some editors) BOM-prefix manifests, and both
    `tomllib.loads` and `json.loads` reject a BOM as a parse error.
    """
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _signal(kind: str, value: str, evidence: str) -> Signal:
    """The sanitization choke point for detected facts."""
    return Signal(
        kind=kind,
        value=sanitize_extracted(value, MAX_VALUE),
        evidence=sanitize_extracted(evidence, MAX_EVIDENCE),
    )


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[Signal] = set()
    unique: list[Signal] = []
    for signal in signals:
        if signal in seen:
            continue
        seen.add(signal)
        unique.append(signal)
    return unique


def _dep_name(spec: str) -> str:
    match = _DEP_NAME_RE.match(spec)
    return match.group(1).lower() if match else ""


def _emit_dep_signals(deps: dict[str, str], signals: list[Signal], *, frontend: bool) -> None:
    """Emit whitelist-vocabulary signals for a {dep-name: evidence-file} map."""
    for dep in sorted(deps):
        evidence = deps[dep]
        if dep in _SERVICE_FRAMEWORKS:
            signals.append(_signal("service-framework", _SERVICE_FRAMEWORKS[dep], evidence))
        if frontend and dep in _FRONTEND_FRAMEWORKS:
            signals.append(_signal("frontend-framework", _FRONTEND_FRAMEWORKS[dep], evidence))
        if dep in _ORM_DEPS:
            signals.append(_signal("data", _ORM_DEPS[dep], evidence))
        if dep in _AUTH_DEPS:
            signals.append(_signal("auth-dep", dep, evidence))


# ── ecosystems ───────────────────────────────────────────────────────


def _scan_python(root: Path, signals: list[Signal]) -> tuple[str, str]:
    name = ""
    description = ""
    deps: dict[str, str] = {}
    manifest_evidence = ""

    text = _read_text(root / "pyproject.toml")
    if text is not None:
        manifest_evidence = "pyproject.toml"
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            data = {}
        project = data.get("project")
        project = project if isinstance(project, dict) else {}
        name = str(project.get("name") or "")
        description = str(project.get("description") or "")
        specs = list(project.get("dependencies") or [])
        optional = project.get("optional-dependencies")
        for group in (optional or {}).values() if isinstance(optional, dict) else ():
            specs.extend(group)
        groups = data.get("dependency-groups")
        for group in (groups or {}).values() if isinstance(groups, dict) else ():
            specs.extend(s for s in group if isinstance(s, str))
        for spec in specs:
            dep = _dep_name(str(spec))
            if dep:
                deps.setdefault(dep, "pyproject.toml")
        scripts = project.get("scripts")
        if isinstance(scripts, dict) and scripts:
            framework = next((t for d, t in _CLI_FRAMEWORKS.items() if d in deps), "console-script")
            signals.append(_signal("cli-entrypoint", framework, "pyproject.toml"))
        tool = data.get("tool")
        if isinstance(tool, dict) and "pytest" in tool:
            signals.append(_signal("test-framework", "pytest", "pyproject.toml"))

    cfg_text = _read_text(root / "setup.cfg")
    if cfg_text is not None:
        parser = configparser.ConfigParser()
        try:
            parser.read_string(cfg_text)
        except configparser.Error:
            pass
        else:
            manifest_evidence = manifest_evidence or "setup.cfg"
            name = name or parser.get("metadata", "name", fallback="")
            description = description or parser.get("metadata", "description", fallback="")
            for line in parser.get("options", "install_requires", fallback="").splitlines():
                dep = _dep_name(line)
                if dep:
                    deps.setdefault(dep, "setup.cfg")

    for requirements in sorted(root.glob("requirements*.txt"), key=lambda p: p.name):
        req_text = _read_text(requirements)
        if req_text is None:
            continue
        manifest_evidence = manifest_evidence or requirements.name
        for line in req_text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            dep = _dep_name(line)
            if dep:
                deps.setdefault(dep, requirements.name)

    if manifest_evidence:
        signals.append(_signal("manifest", "python", manifest_evidence))
        if (root / "src").is_dir():
            signals.append(_signal("package-layout", "src", "src/"))
    if "pytest" in deps:
        signals.append(_signal("test-framework", "pytest", deps["pytest"]))
    _emit_dep_signals(deps, signals, frontend=False)
    return name, description


def _scan_node(root: Path, signals: list[Signal]) -> tuple[str, str]:
    text = _read_text(root / "package.json")
    if text is None:
        return "", ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    signals.append(_signal("manifest", "node", "package.json"))
    name = str(data.get("name") or "")
    description = str(data.get("description") or "")

    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            for dep in block:
                deps.setdefault(str(dep).lower(), "package.json")
    if data.get("bin"):
        signals.append(_signal("cli-entrypoint", "bin", "package.json"))
    for dep, token in sorted(_NODE_TEST_FRAMEWORKS.items()):
        if dep in deps:
            signals.append(_signal("test-framework", token, "package.json"))
    if isinstance(data.get("jest"), dict):
        signals.append(_signal("test-framework", "jest", "package.json"))
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        test_script = str(scripts.get("test") or "")
        if test_script and "no test specified" not in test_script:
            signals.append(_signal("test-script", "npm test", "package.json"))
    for pattern, token in (
        ("jest.config.*", "jest"),
        ("vitest.config.*", "vitest"),
        (".mocharc*", "mocha"),
    ):
        matches = sorted(root.glob(pattern), key=lambda p: p.name)
        if matches:
            signals.append(_signal("test-framework", token, matches[0].name))
    _emit_dep_signals(deps, signals, frontend=True)
    return name, description


def _scan_rust(root: Path, signals: list[Signal]) -> tuple[str, str]:
    text = _read_text(root / "Cargo.toml")
    if text is None:
        return "", ""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return "", ""
    signals.append(_signal("manifest", "rust", "Cargo.toml"))
    package = data.get("package")
    package = package if isinstance(package, dict) else {}
    name = str(package.get("name") or "")
    description = str(package.get("description") or "")
    if data.get("bin"):
        signals.append(_signal("cli-entrypoint", "cargo-bin", "Cargo.toml"))
    elif (root / "src" / "main.rs").is_file():
        signals.append(_signal("cli-entrypoint", "cargo-bin", "src/main.rs"))
    dependencies = data.get("dependencies")
    deps = (
        {str(d).lower(): "Cargo.toml" for d in dependencies}
        if isinstance(dependencies, dict)
        else {}
    )
    _emit_dep_signals(deps, signals, frontend=False)
    return name, description


def _scan_go(root: Path, signals: list[Signal]) -> tuple[str, str]:
    text = _read_text(root / "go.mod")
    if text is None:
        return "", ""
    signals.append(_signal("manifest", "go", "go.mod"))
    module_match = _GO_MODULE_RE.search(text)
    name = module_match.group(1).rsplit("/", 1)[-1] if module_match else ""
    for dep in sorted({m.group(1).lower() for m in _GO_REQUIRE_RE.finditer(text)}):
        if dep.startswith("github.com/gin-gonic/gin"):
            signals.append(_signal("service-framework", "gin", "go.mod"))
        elif dep.startswith("github.com/labstack/echo"):
            signals.append(_signal("service-framework", "echo", "go.mod"))
    if (root / "main.go").is_file():
        signals.append(_signal("cli-entrypoint", "go-main", "main.go"))
    elif (root / "cmd").is_dir():
        signals.append(_signal("cli-entrypoint", "go-cmd", "cmd/"))
    return name, ""


# ── generic markers ──────────────────────────────────────────────────


def _scan_frontend_markers(root: Path, entries: list[str], signals: list[Signal]) -> None:
    if (root / "index.html").is_file():
        signals.append(_signal("frontend-marker", "index.html", "index.html"))
    for extension, token in ((".tsx", "tsx"), (".vue", "vue"), (".svelte", "svelte")):
        first = next((e for e in entries if e.endswith(extension)), None)
        if first is not None:
            signals.append(_signal("frontend-marker", token, first))


def _scan_tests(root: Path, entries: list[str], signals: list[Signal]) -> None:
    for directory in ("tests", "test", "__tests__"):
        if (root / directory).is_dir():
            signals.append(_signal("tests-dir", directory, f"{directory}/"))
    nested = next((e for e in entries if e.endswith("__tests__/") and "/" in e.rstrip("/")), None)
    if nested is not None:
        signals.append(_signal("tests-dir", "__tests__", nested))
    if (root / "pytest.ini").is_file():
        signals.append(_signal("test-framework", "pytest", "pytest.ini"))


def _scan_ci(root: Path, signals: list[Signal]) -> None:
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        files = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")], key=lambda p: p.name)
        for workflow in files:
            signals.append(
                _signal("ci-workflow", "GitHub Actions", f".github/workflows/{workflow.name}")
            )
    if (root / ".gitlab-ci.yml").is_file():
        signals.append(_signal("ci-workflow", "GitLab CI", ".gitlab-ci.yml"))
    if (root / "azure-pipelines.yml").is_file():
        signals.append(_signal("ci-workflow", "Azure Pipelines", "azure-pipelines.yml"))


def _scan_infra(root: Path, entries: list[str], signals: list[Signal]) -> None:
    if (root / "Dockerfile").is_file():
        signals.append(_signal("infra", "docker", "Dockerfile"))
    compose = sorted(
        [*root.glob("docker-compose*.yml"), *root.glob("docker-compose*.yaml")],
        key=lambda p: p.name,
    )
    if compose:
        signals.append(_signal("infra", "docker-compose", compose[0].name))
    terraform = next((e for e in entries if e.endswith(".tf")), None)
    if terraform is not None:
        signals.append(_signal("infra", "terraform", terraform))
    for directory, token in (("k8s", "kubernetes"), ("kubernetes", "kubernetes"), ("helm", "helm")):
        if (root / directory).is_dir():
            signals.append(_signal("infra", token, f"{directory}/"))


def _scan_data(root: Path, entries: list[str], signals: list[Signal]) -> None:
    for directory, token in (
        ("migrations", "migrations"),
        ("alembic", "alembic"),
        ("prisma", "prisma"),
    ):
        if (root / directory).is_dir():
            signals.append(_signal("data", token, f"{directory}/"))
    nested = next((e for e in entries if e.endswith("migrations/") and "/" in e.rstrip("/")), None)
    if nested is not None:
        signals.append(_signal("data", "migrations", nested))
    sql = next((e for e in entries if e.endswith(".sql")), None)
    if sql is not None:
        signals.append(_signal("data", "sql", sql))


def _scan_docs(root: Path, signals: list[Signal]) -> None:
    if (root / "mkdocs.yml").is_file():
        signals.append(_signal("docs-site", "mkdocs", "mkdocs.yml"))
    for conf in ("docs/conf.py", "docs/source/conf.py"):
        if (root / Path(conf)).is_file():
            signals.append(_signal("docs-site", "sphinx", conf))
    docusaurus = sorted(root.glob("docusaurus.config.*"), key=lambda p: p.name)
    if docusaurus:
        signals.append(_signal("docs-site", "docusaurus", docusaurus[0].name))
    docs_dir = root / "docs"
    if docs_dir.is_dir() and any(docs_dir.iterdir()):
        signals.append(_signal("docs-site", "docs-dir", "docs/"))


# ── derivation ───────────────────────────────────────────────────────


def _language_census(entries: list[str]) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for entry in entries:
        if entry.endswith("/"):
            continue
        language = _LANGUAGES.get(Path(entry).suffix.lower())
        if language:
            counts[language] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(language for language, _ in ranked)


def _derive_kind(signals: list[Signal], languages: tuple[str, ...]) -> str:
    kinds = {s.kind for s in signals}
    has_service = "service-framework" in kinds
    has_frontend = "frontend-framework" in kinds
    if has_service and has_frontend:
        return "mixed"
    if has_service:
        return "service"
    if has_frontend:
        return "frontend-app"
    if "cli-entrypoint" in kinds:
        return "cli"
    if "manifest" in kinds:
        return "library"
    return "unknown"
