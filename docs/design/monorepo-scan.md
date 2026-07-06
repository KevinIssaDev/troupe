# Design: monorepo-aware scanning for `troupe init`

**Status:** Signed off by Kevin, 2026-07-06. All bounds, the nested-manifest
tradeoff, and the deferred zero-signal UX item are approved as designed.
Implementation in progress.
**Author:** Wright (Lead)
**Date:** 2026-07-06

## Problem (confirmed, not synthetic)

Real-world repro at `E:\howler`: root has no manifest at all (no
`pyproject.toml`/`package.json`/`Cargo.toml`/`go.mod` at the top level). The
actual projects live one level down — `ui/` (React app: `package.json` with
`react`, `vite.config.ts`, `tsconfig.json`), `client/` (Python package:
`pyproject.toml`, `pytest.ini`, `test/`), `api/` (Python package:
`pyproject.toml`). Running the released `uvx troupe init` (v0.2.0, straight
from PyPI) against this tree produced: `kind = "unknown"` rendered as a
generic "shell project" (the language census picked up shallow `.sh` files
from `ansible/hooks/scripts` at the walk's shallow depth), zero frontend cast
despite the real React app, a generic unspecialized "Backend", and "no tests
detected" despite two real pytest suites.

Root cause, confirmed by reading `src/troupe/discovery/scanner.py`:
`_scan_python`/`_scan_node`/`_scan_rust`/`_scan_go` each check exactly one
path — `root / "pyproject.toml"` etc. — the single directory `scan()` was
invoked on, never any subdirectory. The bounded walk (`_walk()`,
`_MAX_DEPTH = 2`) already collects subdirectory entries (`ui/`, `client/`,
`api/`, and — at depth 2 — files inside them, including `ui/package.json`)
for marker/language-census purposes, but nothing re-checks those directories
for manifests. For this specific repro the walk already *sees*
`ui/package.json` as a depth-2 entry; the gap is purely that the ecosystem
scanners never look at `entries` at all. A second, related repro (a sibling
test copy with `pyproject.toml` nested one level deeper than where `init`
was actually run) is the same root cause with a single nested manifest
instead of several, and is fixed by the same change — see "Single nested
project" below.

## Chosen bounds (headline answer)

- **`_MAX_DEPTH`: 2 → 5.** Depth *N* makes files nested up to *N − 1*
  directories deep visible to the walk (see arithmetic below). Depth 5
  reaches manifests nested up to 4 directories deep from the scanned root,
  covering: single-level splits like howler's (`ui/package.json`, needs
  depth 2 — already reachable today, just unused), Nx/Turborepo-style
  `apps/<name>/`, `packages/<name>/` (depth 3), and deeper domain-organized
  trees like `libs/<domain>/<feature>/package.json` or
  `services/<team>/<service>/pyproject.toml` (depth 4). Beyond that is
  unusual for source-controlled *package* boundaries — as opposed to
  vendored/build output, which the existing skip-dir list
  (`node_modules`, `.venv`, `dist`, `build`, `target`, …) already excludes
  from descent regardless of depth.
- **`_MAX_ENTRIES`: 2000 → 3000.** The walk does no file-content reads — it's
  `iterdir()` + a stat-backed `is_dir()` + a string append per entry.
  Manifest content is only read later, per already-discovered component,
  through the existing 512 KB-capped `_read_text`. 3000 such stat-only
  operations complete in tens of milliseconds on a warm cache (the normal
  case — `troupe init` runs against a repo the user is actively working in)
  and stay well under a second even cold, on a local disk. This is a modest,
  not arbitrary, bump: it exists only to keep the *general* walk (language
  census, nested test/infra/data marker detection) from starving on a wider
  tree now that depth went up, not because component discovery itself needs
  it — see next point.
- **Component discovery costs zero additional filesystem calls.** It is a
  pure in-memory pass over the `entries` list the walk already produced
  (turned into a `set` for O(1) membership checks against known manifest
  filenames). Raising the number of components scanned doesn't multiply
  walk cost at all — the only added cost per extra component is re-running
  the already-cheap, already-capped per-ecosystem manifest reads.
- **`MAX_COMPONENTS = 12`** (new constant, `discovery/scanner.py`, same
  spirit as `ROSTER_CAP = 5` in `advisor.py`). Scanning more components is
  cheap (bullet above), so the cap isn't a cost control — it's a
  **legibility** control, matching the existing roster-cap precedent: a
  proposal that says "monorepo (12 components: …)" is still a thing a human
  can read; "monorepo (47 components: …)" is not. Components beyond the cap
  are not individually scanned; the profile records how many were skipped
  so the proposal can say so honestly rather than silently truncating.

Depth-to-nesting arithmetic (for the record, matches `_walk`'s existing
recursion): `visit(root, 1)` appends root's direct children as depth-1
entries; a child directory is recursed into (becoming depth-2 entries)
only while `depth < _MAX_DEPTH`. So entries are collected through depth
`_MAX_DEPTH` inclusive, and a manifest file nested *N* directories below
root appears as a depth-(N+1) entry. `_MAX_DEPTH = 5` therefore surfaces
manifests with `N ≤ 4`.

## Architecture

### 1. Component-root discovery (new, `discovery/scanner.py`)

Reuses the existing bounded walk — no second search mechanism. After
`_walk(root)` produces `entries` (as today, just deeper), build `entry_set =
set(entries)` once, then:

```python
_MANIFEST_NAMES = ("pyproject.toml", "setup.cfg", "package.json", "Cargo.toml", "go.mod")
MAX_COMPONENTS = 12

def _discover_components(entry_set: set[str]) -> tuple[list[str], int]:
    """Returns (component roots, count skipped past the cap).

    "" denotes the scanned root itself. A directory qualifies once it
    directly contains a known manifest filename; once a directory qualifies,
    nothing under it is considered for a *further* component (avoids
    double-counting a manifest nested inside another package's own tree —
    see Tradeoffs).
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
```

(`sorted()` over paths is safe for parent-before-child ordering: a
directory's own relative path is always a literal string prefix of its
descendants', and a shorter string that is a prefix of a longer one always
sorts first lexicographically — the same property `_walk` already relies on
implicitly.)

`_has_manifest_at(prefix, entry_set)` checks the five exact filenames
(`f"{prefix}/{name}"` or bare `name` at root) plus a `requirements*.txt`
match restricted to that exact directory (not a deeper one) — all pure
`in entry_set` / `startswith`+`endswith` checks, no I/O.

### 2. Per-component scanning (`scan()` orchestration change)

Every existing per-ecosystem function is already parametrized by a root
path — `_scan_python(root, signals)` etc. — and needs **zero changes to
their bodies**. `scan()` runs each one once per discovered component root,
then rewrites only the evidence of the signals that call produced:

```python
def scan(root: Path) -> ProjectProfile:
    root = root.resolve()
    entries = _walk(root)                 # _MAX_DEPTH=5, _MAX_ENTRIES=3000
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
                signals[i] = replace(signals[i], evidence=f"{rel}/{signals[i].evidence}")

    _scan_ci(root, signals)     # unchanged: root-only, see below
    _scan_docs(root, signals)   # unchanged: root-only, see below

    deduped = _dedupe(signals)
    languages = _language_census(entries)   # unchanged: whole-tree, benefits from deeper walk for free
    kind = "monorepo" if len(component_roots) > 1 else _derive_kind(deduped, languages)
    components = tuple(
        sanitize_extracted(c, MAX_EVIDENCE) for c in component_roots if c
    )
    return ProjectProfile(
        name=sanitize_extracted(name or root.name, MAX_NAME),
        description=sanitize_extracted(description, MAX_DESCRIPTION),
        kind=kind,
        languages=languages,
        signals=tuple(deduped),
        components=components,
        components_truncated=skipped,
    )
```

`_scoped_entries(entries, rel)` re-relativizes the full-tree `entries` list
under a component prefix (`f"{rel}/"`, stripped from matching entries; for
`rel == ""` it's the identity — returns `entries` unchanged) so the four
marker-scan functions receive exactly the shape of input they already
expect (root-relative paths), whether the "root" in question is the true
scan root or a nested component directory.

**Why `_scan_ci`/`_scan_docs` stay root-only, unchanged:** a single CI
config or docs site conventionally covers a whole monorepo (one
`.github/workflows/` builds every package; per-component CI/docs configs
are rare in practice and out of scope for v1). Resolved, not left open.

### 3. `kind = "monorepo"` and the "Core" title question — resolved, falls out naturally

`kind` becomes `"monorepo"` whenever more than one component root is found,
checked *before* the existing `_derive_kind` logic and overriding it
unconditionally — the point of the signal is "multi-package structure,"
regardless of what any individual component looks like.

Kevin's question — should `kind == "monorepo"` suppress the "Core" backend
retitle — **resolves itself with no extra code**: `_specialize()` in
`advisor.py` only retitles `backend` to "Core" when
`profile.kind in ("cli", "library")`. Since monorepo repos now get
`kind = "monorepo"` (a distinct value), that condition simply never matches,
and backend keeps its plain catalog title "Backend." This is the right
outcome argued directly: "Core" was designed to read well for a
single-purpose headless project; a monorepo backend spans multiple
services/packages and "Backend" is the more honest umbrella term. No
suppression logic needed — it's a consequence of `kind` gaining a new value,
not a special case bolted onto the specializer.

### 4. Single nested project (the second real repro, folded in)

A repo with **no root manifest and exactly one nested manifest** (the
sibling-test-copy case Kevin mentioned) is not forced into `kind =
"monorepo"` — that label is reserved for `len(component_roots) > 1`. With
exactly one component root, `_derive_kind` runs exactly as it does today,
just against whichever single directory turned out to hold the manifest.
Practically: today this repo profiles as `kind = "unknown"`; under this
design it profiles correctly as `kind = "cli"`/`"library"`/etc., with
`profile.components = ("client",)` (say) recording *where*. This is a
byproduct of the same mechanism, not separate work — confirming Kevin's
"fold in if it's a natural fit" framing.

### 5. `ProjectProfile.components` — new field, additive

```python
@dataclass(frozen=True)
class ProjectProfile:
    ...
    components: tuple[str, ...] = ()          # non-root component paths, e.g. ("api", "client", "ui")
    components_truncated: int = 0             # components found past MAX_COMPONENTS, not individually scanned
```

Both default to values that reproduce today's profiles exactly for
single-root repos (see invariant below). Entries are relative POSIX paths
(no trailing slash, root itself never appears — root is implicit and
carries no prefix), sanitized via the existing `sanitize_extracted`
boundary for consistency with every other repo-derived string (directory
names are technically repo-controlled content too, even though in practice
they're mundane).

`render_project_summary`/`render_project_context` gain one line when
`components` is non-empty:
`- Components: "api/", "client/", "ui/"` (+ `, +N more not scanned (cap reached)`
if `components_truncated > 0`) — still inside the existing
`FRAMING_LINE`-headed block, still quoted values, no change to the
sanitization/framing rules already in place.

`profile_to_json`/`profile_from_json`: additive keys, defaulted with
`data.get("components", [])` / `data.get("components_truncated", 0)` on
read. `profile.json`'s own `"version": 1` stays as-is — same additive
precedent as `casting-state.json`'s `STATE_VERSION` staying at 1 for the
optional `charter` block in the scan-aware-init design.

## Backward-compatibility invariant (hard, verify explicitly)

**When exactly one component root is found and it is the scanned root
itself** — today's single-package case, the overwhelming common case and
the entire existing test suite's assumption — behavior must be byte-for-byte
identical to today:

- `_discover_components` returns `([""], 0)`.
- The per-component loop runs once, with `component_dir = root`,
  `component_entries = entries` (identity, no re-relativization needed),
  and `rel = ""` so the evidence-rewrite branch (`if rel:`) never fires —
  every signal's evidence string is exactly what the unchanged ecosystem/
  marker functions produced, exactly as today.
- `kind = _derive_kind(deduped, languages)` — same call, same inputs,
  because `len(component_roots) == 1` so the `"monorepo"` branch doesn't
  fire.
- `components = ()`, `components_truncated = 0` — both defaults, so
  `ProjectProfile` equality/JSON output is unchanged for every existing
  fixture unless a new field is explicitly asserted.

This must be a named test (`test_single_root_manifest_is_unchanged` or
similar), not just an inference from reading the code — the existing test
suite's assumption is exactly this path, and it's the one thing in this
design that must never regress.

## Tradeoff, stated explicitly (not silently accepted)

The "don't descend further once a component is claimed" rule can, in
principle, cause a real regression: a legitimately independent nested
package intentionally living inside another package's own directory (e.g.
a workspace member nested under a parent crate's `crates/` folder, or a
Python project with an embedded sub-package that ships its own
`pyproject.toml` for a separate editable install) would have its manifest
silently **never scanned by any ecosystem function** — not merged into the
parent, simply invisible; its dependencies, test framework, and frontend
markers don't surface as signals at all.

This is accepted as the v1 default because the more common real-world case
of "a manifest inside another component's directory" is vendored/example/
fixture content (a demo app bundled inside a library's `examples/` folder, a
copied `node_modules`-adjacent template, a test fixture tree that itself
contains a `pyproject.toml`) — treating every nested manifest as its own
cast-relevant component would produce phantom components and spurious
casting signals (e.g. a fixture's embedded React demo triggering a real
frontend-cast recommendation) far more often than it would correctly surface
a legitimate independent nested package. The alternative (scan every
manifest regardless of nesting) trades a rare false-negative for a common
false-positive; this design accepts the false-negative. If real-world
reports show the opposite is more common, the fix is narrow: stop
descending only within recognized vendor/fixture directory names, which is
exactly the kind of hardcoded-name special-casing item 1 of Kevin's
direction rules out for the *general* mechanism — so this would need to be
revisited as a deliberate, separately-argued follow-up, not folded in here.

## Advisor changes (minimal, as expected)

Because evidence paths are already component-prefixed by the time they
reach `advisor.py`, almost nothing there needs to change — `_frontend_rationale`
and `_tester_rationale` already read whatever `first_signal(...)` returns,
so "react in ui/package.json" / "pytest suite in client/tests/" fall out for
free. The one addition: `_backend_rationale` gains a `kind == "monorepo"`
branch (today's fallthrough would produce a generic "owns core logic
(python codebase)" line, which under-communicates a real monorepo):

```python
if profile.kind == "monorepo":
    names = ", ".join(f"{c}/" for c in profile.components) or "multiple packages"
    return f"backend/service code across {len(profile.components)} components ({names})"
```

`_has_code`, `_wants_frontend`, `_wants_devops`, the `data`/`docs-site`
rules — all unchanged; they already reason over signal *kinds*, not
directory locations, exactly as the proposal anticipated.

## Open questions still needing Kevin's call

1. **The "zero-signal / detection may have failed" UX gap** (a *different*,
   smaller item Kevin flagged: right now a zero-signal scan silently
   proposes the minimal Wright+Sawyer fallback with no signal to the user
   that detection may have failed vs. the project genuinely being that
   small). This is **not bundled into this design** — it's a UX/copy change
   to `advisor.py`/`init.py`'s proposal rendering, unrelated to the
   walk/component mechanism, and bundling it would violate the team's
   one-PR-per-change rule for something that doesn't need to ship together.
   Recommend a small fast-follow design note once this lands. Flagging, not
   deciding.
2. **The vendored/nested-package tradeoff above** — I've made a call
   (accept the false-negative) and argued it, but it's a real product
   decision about what "a component" means; Kevin may want it on record as
   a decision rather than an implementation detail.
3. **`MAX_COMPONENTS = 12`** — reasoned from legibility, not cost (cost is
   near-zero either way). If Kevin wants a bigger number because "won't
   cost much" was about more than just depth, that's an easy knob to turn;
   flagging the number as a judgment call, not a hard constraint.

## Test strategy

New/extended fixture trees in `tests/test_discovery.py`:

- **howler-shape**: no root manifest; `ui/` (package.json + react +
  vite.config.ts), `client/` (pyproject.toml + pytest.ini + test/),
  `api/` (pyproject.toml) — asserts `kind == "monorepo"`,
  `components == ("api", "client", "ui")`, frontend signal present with
  evidence `"ui/package.json"`, two distinct test-framework signals with
  component-prefixed evidence, `_wants_frontend`/`_wants_devops` fire
  correctly through `propose_plan`.
- **single-root-manifest** (the hard invariant): today's existing
  python-cli/node-frontend/go-service fixtures re-asserted byte-identical —
  same `name`/`description`/`kind`/`languages`/`signals`, `components == ()`.
- **single-nested-project**: no root manifest, exactly one manifest one
  level down — asserts `kind` derives correctly (not "unknown", not
  "monorepo"), `components == (that dir,)`.
- **nested-inside-component** (the stated tradeoff): a component with its
  own manifest, containing a subdirectory that *also* has a manifest —
  asserts the inner one is not double-counted as a separate component and
  is not scanned (documents the accepted limitation as a passing, asserted
  test, not just prose).
- **depth-and-cap stress fixture**: a synthetic tree with manifests at
  varying depths (some within reach of `_MAX_DEPTH = 5`, at least one
  deliberately beyond it) and more than `MAX_COMPONENTS` sibling packages —
  asserts components beyond depth are simply invisible (documented
  limitation, not a crash), components beyond the cap are not individually
  scanned but `components_truncated` reflects the count, and the whole scan
  completes without hitting `_MAX_ENTRIES` in a way that drops in-reach
  components (i.e., the fixture's total entry count stays comfortably under
  3000 — this test is about the cap *mechanism*, not about proving the
  literal 3000/12 numbers are exactly right for production-sized repos).
- **injection regression**: existing hostile-manifest-description fixture
  re-run once as a nested component (`ui/package.json` with an adversarial
  `description`) to confirm sanitization/framing still holds when the
  manifest isn't at the scanned root.

Extend `tests/test_init.py`/proposal-rendering tests: monorepo proposal
output shows `Components: ...` line and (if relevant) the "Core" title is
*not* applied to a monorepo's backend member.

## Scope

**In this PR**, if signed off as designed:
- `discovery/scanner.py`: `_MAX_DEPTH`/`_MAX_ENTRIES` bump, `_discover_components`,
  `_has_manifest_at`, `_scoped_entries`, `scan()` orchestration rewrite,
  `MAX_COMPONENTS` constant. No changes to the bodies of `_scan_python`/
  `_scan_node`/`_scan_rust`/`_scan_go`/`_scan_frontend_markers`/`_scan_tests`/
  `_scan_infra`/`_scan_data` — only their call sites change.
- `discovery/profile.py`: `ProjectProfile.components`/`components_truncated`
  fields, `render_project_context`/`render_project_summary` components line,
  `profile_to_json`/`profile_from_json` additive keys, `KINDS` gains
  `"monorepo"`.
- `discovery/advisor.py`: `_backend_rationale` monorepo branch. Everything
  else unchanged (see "Advisor changes" above).
- Tests per the strategy above.

**Explicitly not in this PR:** the zero-signal-detection UX gap (item 1
above); per-component sub-profiles as first-class casting units (v1 still
proposes one flat roster over the aggregate profile, same as today — a
monorepo doesn't get per-package cast members); JVM/.NET/Ruby/PHP ecosystem
support (unrelated, already deferred in scan-aware-init.md).

---

## Proposed decision entries (copy into `.troupe/decisions.md` after sign-off)

### 2026-07-06: Monorepo-aware scanning — component discovery reuses the single bounded walk, deepened
**By:** Wright (design), Kevin (sign-off pending)
**What:** `discovery/scanner.py`'s bounded walk deepens from `_MAX_DEPTH = 2`/`_MAX_ENTRIES = 2000` to `_MAX_DEPTH = 5`/`_MAX_ENTRIES = 3000`. A new in-memory pass over the walk's own output (`_discover_components`, zero extra filesystem calls) finds every directory that directly contains a known manifest filename, without descending further below a directory once it's claimed as a component. Each per-ecosystem scan function (unchanged) runs once per discovered component root; evidence paths are prefixed with the component's relative path. `kind = "monorepo"` when more than one component root is found; capped at `MAX_COMPONENTS = 12` for legibility (not cost — extra components are nearly free to scan, just not free to display).
**Why:** `troupe init` against a real monorepo (no root manifest, projects one level down) profiled as "unknown" and produced zero frontend cast despite a real React app, because the ecosystem scanners only ever checked the single directory `scan()` was pointed at. Detection must be fully dynamic (manifest-filename presence, no hardcoded directory names) per explicit direction; depth 2 was reasoned as too shallow for realistic monorepo layouts (Nx/Turborepo-style `apps/*`/`packages/*` alone need depth 3).

### 2026-07-06: Single-root-manifest byte-identical invariant is load-bearing
**By:** Wright (design), Kevin (sign-off pending)
**What:** When exactly one component root is found and it is the scanned root itself, `scan()` must produce a `ProjectProfile` byte-identical to today's (same `name`/`description`/`kind`/`languages`/`signals`; `components = ()`). This is a named, explicitly asserted test, not an inference.
**Why:** This is the overwhelming common case and the assumption underlying the entire existing scan-aware-init test suite; the monorepo fix must not regress it.

### 2026-07-06: Nested-inside-component manifests are not separately scanned — accepted tradeoff
**By:** Wright (design), Kevin (sign-off pending)
**What:** Once a directory is claimed as a component root, any manifest found further inside it is never scanned by any ecosystem function — not merged into the parent, simply invisible to detection. No hardcoded vendor/fixture directory names are used to distinguish "legitimate nested package" from "vendored/example content nested inside a component."
**Why:** Real repos far more often nest a nested manifest as vendored/example/fixture content than as a legitimate independent sub-package; treating every nested manifest as its own component would produce phantom components and spurious casting signals (e.g. a bundled demo app triggering a frontend-cast recommendation) more often than it would correctly surface a real nested package. Revisit only if real-world reports show the opposite.
