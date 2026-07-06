# Design: `/troupe-explore`

**Status:** Signed off by Kevin, 2026-07-06. Force-refresh confirmed; wording
set; implementation in progress on `feat/troupe-explore` (branched fresh off
`main` after PR #1 merged).
**Author:** Wright (Lead)
**Date:** 2026-07-06

## Problem

Scan-aware init (`docs/design/scan-aware-init.md`, PR #1, still open) seeds
every cast member with a shallow, deterministic project summary
(`project_context`: name, description, stack, evidence-backed facts). It
deliberately does not go deeper — no LLM pass, no per-file reading — because
init must stay offline, instant, and free.

Kevin's earlier suggestion was to close that gap with an `--enrich` flag
(one bounded `claude -p` call at init time). Kevin has since rejected that
direction in favor of a different mechanism entirely, for two independent
reasons:

1. Init is the wrong moment for deep exploration — it's a zero-cost,
   zero-auth first command; shelling out to `claude -p` there re-introduces
   the budget/timeout/env-sanitization machinery the scan-aware-init design
   explicitly argued was disproportionate for init (see that doc's
   "Decision: deterministic Python heuristics" section).
2. A **self-triggering** exploration conditional — e.g. "if your history.md
   still looks like boilerplate, go explore" wired into the charter or
   `agent.md` templates — was floated and explicitly rejected. Conditionals
   like that fire unpredictably on every spawn (any task can trigger a
   surprise multi-file read-and-write pass) and cause history.md to mutate
   during unrelated work. Findings-gathering must be deliberate and
   user-invoked, never ambient.

The fix: a **user-invoked slash command**, `/troupe-explore`, that fans the
*live* orchestrator session out to every active cast member in parallel, each
reading their own ownership area and appending what they find to their own
`history.md`. This is squad's post-cast exploration step (already anticipated
in scan-aware-init's roadmap), landed as a command instead of a flag.

## Mechanism: `.claude/commands/troupe-explore.md`

Verified against current Claude Code docs (2026-07-06): `.claude/commands/
<name>.md` is the correct, fully supported way to define a project-scoped
`/name` slash command. Commands are conceptually being folded into the
broader "skills" model in the docs, but existing `.claude/commands/*.md`
files are explicitly still honored, unchanged — no migration needed for a
new file written today.

Two mechanism choices this design rules out:

- **`context: fork` + `agent: <name>` frontmatter.** That routes the *entire
  command* to one named subagent. Wrong shape here — we want the live
  orchestrator (whoever is running Claude Code when the user types the
  command) to read the roster and spawn *multiple* named cast members
  itself, exactly like a lead fanning out teammates via the `Agent` tool in
  normal operation. No frontmatter routes to multiple agents at once; the
  prompt body has to do the fan-out itself.
- **A new `troupe explore` Python CLI subcommand.** Explicitly out of scope
  per Kevin's spec — this is a Claude Code-side orchestration action (spawn
  subagents, have them read/write files), not something the `troupe` CLI
  binary does or could do (it has no way to invoke Claude Code subagents).

Naming: a built-in read-only agent type named `Explore` already exists in
Claude Code. A command named `/explore` would be confusable with it —
`troupe-explore` is unambiguous and is the exact name specified; not
shortened.

### Command file content

```markdown
---
description: Have each active cast member read their own ownership area and record findings in their own history.md.
allowed-tools: Agent, Read, Glob, Grep
---

# /troupe-explore

Deliberate, one-shot exploration: have every active cast member read the
part of this codebase they own and write down what they find. This command
is the *only* trigger for this — cast members never do this on their own
mid-task.

## Steps

1. Read `.troupe/team.md` and list every row in the `## Cast` table with
   `active` status. Do not assume any particular names or roles — the
   roster in this repo is whatever `team.md` says, and it will differ
   project to project.
2. For each active member, read `.troupe/agents/<slug>/charter.md` (the
   charter path is given in the table) to get their exact `## Ownership`
   bullets and title. Derive `<slug>` from the charter path in the table
   (e.g. `.troupe/agents/mason/charter.md` → slug `mason`).
3. Confirm a matching agent type exists at `.claude/agents/<slug>.md`. The
   cast agent type to spawn is that file's own name (the slug), never a
   hardcoded name. If a roster row has no matching `.claude/agents/<slug>.md`,
   skip that member and note it in your final summary — do not guess at a
   different agent type.
4. Spawn every matched member **in parallel, in a single message** (one
   `Agent` tool call per member, all in the same turn) with `subagent_type`
   set to their slug. Each spawned agent's prompt should instruct them to:
   - Explore the codebase within their own ownership area only (the bullets
     from their charter) — read enough real code to form specific
     observations, not just directory listings.
   - Look for things a teammate would want written down: architecture and
     key conventions, patterns worth reusing, gaps, risks, anything
     surprising or non-obvious.
   - Append a new section to their own `.troupe/agents/<slug>/history.md`,
     under the existing `## Learnings` heading, headed
     `## Explore <today's date, YYYY-MM-DD>`, with findings as bullet points.
   - Make no other file changes. This is read-and-record only.
5. Once all spawned members return, summarize for the user what each member
   found (or report which were skipped and why).

## Notes

- Re-running this command is expected to happen more than once as a repo
  evolves. Each run's findings land under their own dated heading, so
  history.md accumulates a visible log of explore passes rather than
  silently overwriting earlier findings. Do not attempt to detect or dedup
  against a previous run — the dated heading already makes repeat runs
  legible to a human reading history.md.
- Do not fork yourself for this — the whole point is spawning the *named
  cast members* (their own agent types), not a generic research fork.
```

Notes on the design of the prompt itself:

- **No hardcoded names or roles anywhere** — the command file ships
  identically to every troupe-scaffolded repo, and rosters differ (this
  repo: Wright/Mason/Webster/Sawyer; another repo could have a completely
  different cast and role mix). Every reference to a cast member is
  "read it from team.md/charter.md."
- **`allowed-tools: Agent, Read, Glob, Grep`** pre-approves the fan-out so
  the user isn't prompted once per spawned member. `Agent` is the one that
  matters; `Read`/`Glob`/`Grep` cover the orchestrator's own roster/charter
  reads in steps 1–3. The spawned members' own tool access is whatever
  their `.claude/agents/<slug>.md` definition already grants (unchanged by
  this command).
- **Idempotency is handled by the dated heading, not by any state file or
  flag.** This matches Kevin's explicit steer: no complex tracking, the
  accumulating log is the feature, not a bug.

## Where this file lives: scaffolded, not static-shipped

Two options:

1. Ship `.claude/commands/troupe-explore.md` once, folded into troupe's own
   *package* docs/tooling — never written into a user's scaffolded repo.
2. Template it like every other file troupe writes: source of truth at
   `src/troupe/templates/commands/troupe-explore.md`, written into each
   scaffolded repo's `.claude/commands/troupe-explore.md` by `scaffold.py`,
   refreshed by `upgrade.py`.

**Decision: (2), scaffolded — following the exact pattern already
established for `.claude/hooks/*.py`.**

Verified against current `scaffold.py`/`upgrade.py` (both read from
`src/troupe/templates/` via `importlib.resources.files`):

- The command file needs **no per-project substitution** — it reads
  `team.md`/charter.md live, at command-run time, in the target repo. So
  unlike `charter.md`/`history.md`/`team.md` (which go through
  `string.Template.substitute` with `project_context`/`cast_table`), it is
  a **static** file, exactly like `hooks/troupe_*.py` and `policy.json`.
- `scaffold.py` already has the static-file pattern fully built:
  `_write_if_missing(root / ".claude" / "hooks" / script, files("troupe.templates").joinpath(f"hooks/{script}").read_text(...), result)`
  in the `scaffold()` function body. The command file is one more line of
  the same shape:
  `_write_if_missing(root / ".claude" / "commands" / "troupe-explore.md", files("troupe.templates").joinpath("commands/troupe-explore.md").read_text(encoding="utf-8"), result)`
- `upgrade.py` already refreshes hook scripts and agent definitions
  unconditionally (`_refresh`, not `_write_if_missing` — it overwrites
  even if the user edited the file, because those are documented as
  troupe-owned, not-for-hand-editing artifacts: "Troupe-owned (refreshed to
  current templates): `.claude/hooks/*.py`... `.claude/agents/{slug}.md`").
  The command file belongs in that same bucket, not the "never touched"
  bucket (team.md, decisions.md, charters, histories) — it's a mechanism
  file, not something a user is expected to hand-tune per repo. Add one
  more `_refresh(root / ".claude" / "commands" / "troupe-explore.md", ..., result)`
  call to `upgrade()` alongside the hook-script loop.
- This makes the command travel with the cast (point of the whole feature
  — it must exist wherever `.claude/agents/*.md` exists) and versioned the
  same way everything else troupe owns is versioned: `troupe upgrade` picks
  up prompt-wording improvements later without the user re-running `init`.

Net new files/edits for implementation (not done in this pass — design
only):

- New: `src/troupe/templates/commands/troupe-explore.md` (content above).
- `src/troupe/scaffold.py`: one `_write_if_missing(...)` call for the new
  path, alongside the existing hooks loop.
- `src/troupe/upgrade.py`: one `_refresh(...)` call for the same path,
  alongside the existing hooks loop.
- Tests: extend `tests/test_init.py`/scaffold tests to assert
  `.claude/commands/troupe-explore.md` is created on init; extend upgrade
  tests to assert it's refreshed to the latest template content (mirrors
  existing hook-script assertions — no new test file needed).

## `troupe init`'s one-line message change

Per Kevin's spec, this is the **only** change to `init.py` itself — no new
flags, no scanning changes, otherwise byte-identical.

`src/troupe/commands/init.py`, end of `_echo_result()`:

```python
# before
    troupe_dir = result.root / ".troupe"
    typer.echo(f"Team state: {troupe_dir}")
    typer.echo("Next: commit .troupe/ and .claude/ so the team travels with the repo.")

# after
    troupe_dir = result.root / ".troupe"
    typer.echo(f"Team state: {troupe_dir}")
    typer.echo("Next: open Claude Code and run /troupe-explore, or tell the team directly.")
```

**Signed off by Kevin (2026-07-06): the new line *replaces* the old
"commit .troupe/..." line rather than adding a second line** — one "Next:"
line total, matching the exact wording Kevin specified. (Committing the
roster is still true and covered elsewhere — see the repo's own
`troupe-repo-rules` guidance that `.troupe/`/`.claude/` are deliberately
*not* committed to troupe's own repo; the generic scaffold message shouldn't
be the more prominent of two competing "Next:" lines for other projects
either.) Suggested test pin: extend whatever existing test asserts on
`_echo_result` / init stdout (the current "Next: commit..." assertion, if one
exists in `tests/test_init.py`) to assert the new wording instead; if no such
assertion currently exists, add one rather than leaving the new line
unpinned.

## `docs/design/scan-aware-init.md` cleanup: drop `--enrich`

Kevin's decision is to drop `--enrich` **entirely** from the roadmap, not
just defer it further — this command is the resolution of that roadmap
item, and `--enrich`'s premise (an LLM prose pass *at init time*) is
superseded by explore's better-fitting shape (deliberate, user-invoked,
post-cast, per-member). Two spots in that doc reference it:

1. **"Decision: deterministic Python heuristics..." section** (~line 94-99),
   the paragraph starting "The extension point (v2): a `--enrich` flag on
   init...". Replace with a superseded note pointing at this doc, rather
   than deleting silently (keeps the historical reasoning legible for
   anyone reading the old design later):

   ```markdown
   The extension point once sketched here — a `--enrich` flag running one
   bounded `claude -p` call at init time — is **dropped, not shipped**.
   Superseded by `/troupe-explore` (`docs/design/troupe-explore.md`): a
   user-invoked slash command that fans out to every cast member after
   casting, each reading their own ownership area in the *live* Claude Code
   session and recording findings in their own `history.md`. That shape
   fits deep exploration better than an init-time LLM call — it's
   deliberate rather than automatic, and it naturally splits by cast
   member's ownership instead of producing one generic prose blob.
   ```

2. **"### Later (in likely order)" section** (~line 461-472). Remove the
   `--enrich` bullet outright; update the existing `troupe explore` bullet
   (already anticipated there) to point at the now-drafted design instead
   of describing it from scratch:

   ```markdown
   ### Later (in likely order)

   - `troupe explore` — landed as a slash command, not an init flag; see
     `docs/design/troupe-explore.md`.
   - More ecosystems: JVM, .NET, Ruby, PHP; real monorepo/multi-package
     profiles (per-package sub-profiles).
   - `doctor` stack-drift check against `.troupe/profile.json`.
   - Recast/retire tooling (fixing the Websters that already exist).
   ```

3. Also touches the "Resolved questions" recap (~line 485-486, item 6: "LLM
   pass: deferred to v2 behind `--enrich`") — reword to state it was dropped
   rather than deferred, so a reader of that section isn't left expecting
   a future `--enrich`:

   ```markdown
   6. **LLM pass:** dropped from the roadmap — `--enrich` is not shipping;
      superseded by `/troupe-explore` (see `docs/design/troupe-explore.md`).
   ```

## Branch situation

`feat/scan-aware-init` is **still open** as PR #1
(https://github.com/KevinIssaDev/troupe/pull/1, state: OPEN) — it has not
landed on `main`. Per the repo rule of one PR per change (`.troupe` memory:
"feature branches only... one PR per change"), this feature should **not**
pile onto that open, unrelated PR. Recommendation: hold this work until
PR #1 merges, then cut a fresh branch off `main` for `troupe-explore`
specifically (e.g. `feat/troupe-explore`). If PR #1's merge is going to be
delayed and Kevin wants to unblock this sooner, the alternative is to branch
`feat/troupe-explore` off `feat/scan-aware-init` now and rebase it onto
`main` once #1 lands — but that's extra rebase overhead for a small feature
with no real dependency on #1's code (this design touches different files:
`scaffold.py`/`upgrade.py` calls are additive one-liners, no conflict
expected either way). Plain wait-then-branch-off-main is simpler and is
the default unless Kevin wants to parallelize.

## Scope confirmation

Single PR, matching Kevin's spec exactly:

- `src/troupe/templates/commands/troupe-explore.md` (new file, content
  above).
- `src/troupe/scaffold.py`: one `_write_if_missing` line.
- `src/troupe/upgrade.py`: one `_refresh` line.
- `src/troupe/commands/init.py`: one new `typer.echo` line.
- `docs/design/scan-aware-init.md`: the three edits above (supersede
  `--enrich`, drop it from "Later", reword resolved-question 6).
- Tests: extend existing scaffold/upgrade test assertions to cover the new
  file; extend (or add) an init-stdout assertion for the new echo line. No
  new test file, no new Python module.

No new CLI subcommand, no charter/agent.md template changes, no
self-triggering conditional anywhere.

## Resolved (Kevin's sign-off, 2026-07-06)

1. **Branch timing:** PR #1 merged to `main`; `feat/troupe-explore` branched
   fresh off `main` per the recommendation above.
2. **Message wording:** set exactly to "Next: open Claude Code and run
   /troupe-explore, or tell the team directly." — replacing the old
   "commit .troupe/..." line, not adding alongside it (see the `init.py`
   section above).
3. **Command-file bucket:** confirmed force-refresh — `troupe-explore.md`
   goes through `upgrade.py`'s `_refresh` alongside hook scripts and agent
   definitions, same as originally proposed.
