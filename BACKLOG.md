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

## 2026-07-07: decisions.md has no archival — not urgent yet, but the ceiling should be a hook change, not a new "Scribe" agent

**Where:** `src/troupe/templates/hooks/troupe_decision_log.py` (the
`TaskCompleted` hook that auto-appends one entry per completed task);
`.troupe/decisions.md` itself.

**Context:** Kevin asked whether troupe has anything like Squad's Scribe
(`E:\squad\.squad\agents\scribe\charter.md`) — a dedicated cast member,
always spawned `mode: "background"`, whose whole job is merging a
decisions inbox into `decisions.md`, enforcing a two-tier size-based
archival ceiling (30-day archive if >20KB, 7-day archive if still >50KB
after that), writing per-session logs under `.squad/log/`, propagating
cross-agent updates, and auto-committing `.squad/` to git.

**What troupe actually has, verified by reading the hook directly:**
`troupe_decision_log.py` appends one fixed-format entry
(`### <date>: Completed — <task name>` / `**By:** troupe (TaskCompleted
hook)` / one-line `**What:**`) per completed task, and nothing else. No
archival, no size ceiling, no session logs, no cross-agent propagation, no
auto-commit, and no dedicated spawned agent — it's a stdlib-only hook
script invoked by the harness, not a cast member. Every one of Squad's
gaps is real; none of it exists in troupe today.

**Is unbounded growth a real near-term problem?** Partially yes, sooner
than "premature" would suggest: this repo's own `decisions.md` is already
46KB after about one week of active work — past Squad's own 20KB Tier-1
threshold already, and roughly halfway to its 50KB Tier-2 threshold. At
this rate a few more weeks of a project this active would clear 50KB. That
said, "large file" and "actually broken" aren't the same thing yet: nothing
currently reads `decisions.md` in a way a large size actually harms —
cast members read it once at task start (a few hundred KB of text is not
an LLM-context problem at today's model context windows), and it isn't
executed or parsed by any tool that would choke on size. So: worth having
a plan, not worth an emergency fix.

**Does a dedicated always-background "Scribe" cast member fit troupe's
model?** No — checked `src/troupe/casting/roles.py` and the whole
`casting/` package for anything resembling Squad's `mode: "background"`
concept and found nothing: troupe's cast members are Task-tool subagent
definitions (`.claude/agents/{slug}.md`) spawned on demand, by name, when
the lead or user decides a task needs them (see `/troupe-explore`'s
explicit fan-out, or a direct `Agent` call) — there is no primitive for
"this cast member is always running in the background regardless of what
the user is doing," and no code anywhere spawns an agent automatically on
a schedule or as a side effect of other work (the closest thing, Reeve, is
a separate poll loop / `claude -p` subprocess mechanism, not a
Task-spawned cast member, and it runs unattended by explicit design, not
"always in the background during a session"). Grepping for any
`git add .troupe` / `git commit` call anywhere in `src/troupe/` also
turned up nothing — troupe has no auto-commit mechanism at all today, and
this repo's own dogfooding choice is not to commit `.troupe/` in the first
place (git-excluded via `.git/info/exclude`), so Scribe's auto-commit step
wouldn't even apply here without first reversing that separate decision.
Bolting on a Squad-style always-background agent would mean inventing a
spawn primitive troupe has no other use for, just to host archival logic.

**Recommendation:** Don't build a Scribe-equivalent agent. If/when
decisions.md's size actually becomes a problem (a concrete trigger:
crosses ~50KB, or a cast member visibly struggles to find recent entries),
the better-fitted fix is a small, size-gated archival step added to the
*existing* mechanisms that already touch `decisions.md` — either
`troupe_decision_log.py` (check size before appending; if over a
threshold, move entries older than N days to `decisions.archive.md` before
writing the new one) or the new `troupe charter append`/`edit` CLI once it
ships (same file, same "unconditional auto-log" pattern) — not a new
spawned cast member. This matches troupe's existing architecture (hooks +
CLI commands doing narrow, deterministic file maintenance) rather than
importing Squad's "dedicated agent for memory hygiene" pattern wholesale.
Not implemented here — this is a recommendation, filed because the
finding is concrete (46KB today, no ceiling anywhere) even though the fix
isn't urgent enough to build unprompted.
