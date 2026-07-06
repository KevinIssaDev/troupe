# Backlog

Specific, actionable follow-ups found while re-reading the newest code
(scan-aware init's scanner/advisor, monorepo-aware scanning,
`/troupe-explore`) during a documentation-accuracy pass. Weighted toward
that code deliberately — it's had the least time to prove itself, versus
the hardened M0–M7 core (reeve, casting, charters, scaffold), which gets
less scrutiny here. Dated entries; add new ones at the bottom.

## 2026-07-07: `_backend_rationale`'s monorepo branch mis-attributes and undercounts when the root itself is a component

**Where:** `src/troupe/discovery/advisor.py`, `_backend_rationale`, the
`profile.kind == "monorepo"` branch.

**What's wrong:** For a repo shaped like "root has its own manifest (real
backend code) plus one nested component of a different ecosystem" (e.g. a
Python API at the root, a React app in `ui/`), `scan()` correctly finds two
component roots (`""` and `"ui"`) and classifies the profile as
`kind="monorepo"`. But `ProjectProfile.components` only holds *non-root*
component paths (`("ui",)` — the root is filtered out by `if c` in
`scan()`), and `_backend_rationale`'s monorepo branch names and counts
straight from `profile.components`. Reproduced live: `pyproject.toml` at
root + `ui/package.json` (react dep) yields the backend proposal rationale
**"backend/service code across 1 components (ui/)"** — it cites the
frontend-only directory as backend evidence and its count excludes the root
component that's the actual reason backend got cast at all. No test in
`tests/test_discovery.py` covers this shape; the existing monorepo tests
(`test_howler_shape_profiles_as_monorepo`,
`test_domain_organized_monorepo_different_shape_than_howler`) are all
root-less, multi-package layouts, not "root manifest + one nested app."

**Suggested fix:** `_backend_rationale`'s monorepo branch should reason from
`component_roots` semantics, not just `profile.components` — e.g. name only
components that actually carry backend/service evidence (check each
component's own signals) rather than listing every component indiscriminately,
and count/word the root itself explicitly when it's one of the components
("root plus N nested component(s)" vs "N components" when root isn't one).

## 2026-07-07: Component cap (`MAX_COMPONENTS = 12`) selects by discovery/alpha order, not by shallowness

**Where:** `src/troupe/discovery/scanner.py`, `_discover_components`.

**What's wrong:** Once 12 component roots are found, the 13th+ are counted
in `components_truncated` and dropped — but which 12 "win" depends on
`sorted(entry_set)` order (lexicographic path order), not depth or
plausible significance. A repo with a handful of genuinely top-level
components (e.g. `web/`, `worker/`) and a deeply-nested pile of packages
whose paths happen to sort earlier alphabetically (e.g. `apps/*/packages/*`)
could have a real top-level component silently pushed past the cap in favor
of nested ones. Not a correctness bug (the cap and the "not individually
scanned" framing are both by design, per the signed-off monorepo-scan
design), but the selection *order* was never a stated design choice — it's
an accident of using `sorted()` for the unrelated (and necessary)
parent-before-child ordering guarantee.

**Suggested fix:** When truncating, prefer shallower component roots over
deeper ones (sort candidates by depth, then path, before applying the cap)
so a real top-level split is never dropped in favor of something nested
three levels down.

## 2026-07-07: `render_project_context`'s flat 8-signal cap doesn't scale to monorepos

**Where:** `src/troupe/discovery/profile.py`, `render_project_context`
(`if shown >= 8: break`).

**What's wrong:** The cap was sized for a single-project profile (manifest,
CLI entrypoint, one test framework, one CI system, etc. — 8 is generous).
For a monorepo profile, every component's signals are flattened into the
same `profile.signals` sequence and the same global cap of 8 applies across
*all* components combined. A 4-5 component monorepo where each component
contributes 2-3 signal kinds (manifest, test-framework, frontend-framework)
will silently truncate the charter/history seed to the first couple of
components in signal order — the seeded `project_context` a later-listed
component's specialized cast member reads may not mention their own
component at all.

**Suggested fix:** Either raise the cap when `profile.kind == "monorepo"`,
or guarantee at least one signal per component before applying an overall
cap (fair round-robin rather than first-N).

## 2026-07-07: `ProjectProfile.notes`'s docstring is stale after `--enrich` was dropped

**Where:** `src/troupe/discovery/profile.py`, line ~69:
`notes: str = ""  # reserved for v2 LLM enrichment`.

**What's wrong:** The 2026-07-06 decision ("`--enrich` is dropped from the
roadmap, superseded by `/troupe-explore`") retired the `--enrich` flag
entirely, but this field comment (and a matching one in
`docs/design/scan-aware-init.md`'s `ProjectProfile` sketch) still reads as
if a v2 LLM-enrichment pass populating `notes` at init time is still on the
roadmap. It isn't — `/troupe-explore` writes to each member's `history.md`
instead, and nothing currently writes `ProjectProfile.notes` at all. Cheap
fix, but worth doing before a future contributor reads the comment and
resurrects `--enrich`.

**Suggested fix:** Reword to something like `# reserved for future use;
not populated by init or /troupe-explore` (or drop the field until
something actually needs it — check for any remaining reader before
removing).

## 2026-07-07: `/troupe-explore`'s fan-out has none of Reeve's cost/turn/time ceilings

**Where:** `src/troupe/templates/commands/troupe-explore.md` (the fan-out
prompt).

**What's wrong:** Reeve (`troupe watch --execute`) is designed with three
independent per-run ceilings plus two accumulating cost ceilings before it's
allowed to touch a real repo unattended. `/troupe-explore` fans out to every
active cast member (up to `ROSTER_CAP = 5`) in parallel with no analogous
bound — each spawned member does an open-ended "read enough real code to
form specific observations" pass with no turn/token/cost limit stated
anywhere in the command file. This is very likely fine in practice (it's
user-invoked, interactive, and capped at 5 members by the roster cap), but
it's an asymmetry nobody has stated as a deliberate tradeoff the way
Reeve's ceilings were — worth either a short explicit note in
`docs/design/troupe-explore.md` confirming "no ceiling needed, here's why"
or, if repeat runs on large repos turn out to be expensive in practice, an
actual bound.

## 2026-07-07: Zero-signal detection-failed UX — confirmed still open, not yet a tracked issue anywhere

**Where:** `src/troupe/discovery/advisor.py` (`propose_plan`), decision log
entry "2026-07-06: Zero-signal detection-failed UX is deferred as a
separate fast-follow."

**Status check (not a new finding, a confirmation):** re-read `propose_plan`
directly — a profile with zero signals and no languages still silently
proposes the minimal lead+tester cast, with no "detection may have failed"
signal anywhere in the printed proposal. The deferral is still accurate;
nothing since has touched this. Flagging because it's exactly the kind of
first-five-minutes paper cut ("I ran `init` on my repo and got two people
with generic charters, is that right or did something break?") that will
generate a real user report the moment someone outside this troupe runs
`init`. Recommend actually opening a GitHub issue for it (labeled `troupe`
so Reeve can eventually pick it up) rather than leaving it as a decisions.md
paragraph nobody's assigned to.

## 2026-07-07: Nested-manifest exclusion (accepted tradeoff) has no escape hatch

**Where:** `src/troupe/discovery/scanner.py`, `_discover_components`
docstring; decision "Nested-inside-component manifests are not separately
scanned — accepted tradeoff."

**What's wrong:** Once a directory is claimed as a component root, any
manifest nested further inside it is invisible to detection, permanently,
with no way for a user to override it — this is a scan/discovery-level
exclusion that happens before `--roles` or any other CLI flag has a chance
to matter. The design doc reasons (correctly, per the stated evidence) that
this is usually the right default. But for the minority case where a
project genuinely does nest an independent sub-package inside another
component's directory, there's currently no way to get that sub-package
detected short of restructuring the repo. Not urgent (explicitly "revisit
only if real-world reports show the opposite" per the decision), just
noting there's no escape hatch today if that revisit happens — the fix
would need a new mechanism (e.g. a `.troupe/scan-overrides` allowlist),
not a tweak to the existing rule.
