# Changelog

## 0.5.2 (2026-07-09)

- README rewritten from scratch for readers evaluating the project,
  not maintainers of it — matches the current CLI (the removed
  scan-at-init design is gone from the docs) and leads with a plain
  "put them to work" example addressed to the team.
- Added a standalone Install section up top (`uvx troupe init`, with
  `uv tool install` / `pip install` as the persistent-install
  alternative).
- Cleaned up `troupe init`'s terminal output: a one-line summary plus
  a numbered "Next steps" block instead of a flat run of sentences,
  with wording that doesn't assume the reader knows an older version.

## 0.5.1 (2026-07-09)

- `/troupe-setup` proposals now show a role emoji per cast member,
  and scaffolding gains two new team-memory files alongside each
  member's `history.md`: `focus.md` (overwrite-in-place snapshot of
  current work) and `wisdom.md` (append-only log of distilled,
  reusable patterns). `troupe doctor` checks for their presence.
- Clarified in the scaffolded `decisions.md`/`directives.md` templates
  that standing ground rules ("never commit X", "plans go in Y")
  belong in `directives.md`, not `decisions.md` — each file now points
  at the other so an agent doesn't misfile a rule as a one-off
  decision.

## 0.5.0 (2026-07-08)

- New `troupe charter` command — structured, ungated charter edits for
  cast members (`--add`, `--edit`, etc.), applied directly instead of
  going through a propose/approve gate. Proposal paths are guarded
  against path-traversal `NAME` arguments, and charter field values
  are rejected outright if they contain newlines to keep the file
  format safe.
- `troupe init` no longer runs a deterministic project scanner to
  guess a cast for you. A bare `init` now casts nobody, leaving the
  team empty until you run `troupe cast` or the new `/troupe-setup`
  slash command, which walks the roster changes and batches them into
  a single `troupe cast` call. The old scanner subsystem and its
  guidance text were removed; `troupe doctor`'s advice after a bare
  init was updated to match the new (cast-nobody) behavior.
- Fixed `.claude/agents/` not being created unconditionally, which
  meant Claude Code's own file watcher could miss it depending on
  scaffold order.

## 0.4.0 (2026-07-07)

- New `troupe cast` command — grow or retire the cast after `init`.
  `--add-role <role>` casts an additional member into a role using the
  same gap-fill scaffolding as `init`; `--retire <name>` archives an
  active member: the assignment is marked retired in casting-state
  (never deleted), the compiled agent definition is removed, and the
  member's row leaves `team.md` — their charter and history stay
  untouched. Retired names are never reallocated to new members (this
  also fixes a latent bug where name allocation only checked active
  members, contradicting the never-reuse rule). Cast changes log their
  own `decisions.md` entry. A `/troupe-cast` slash command ships
  alongside, scaffolded and refreshed via `troupe upgrade` like
  `/troupe-explore`.
- The session-context hook now teaches the coordinating (main) session
  to delegate: sessions with no agent identity get an orchestrator
  block stating that work in a cast member's ownership area goes to
  that member by default, and doing specialist work inline is a
  failure mode. Roster lines are enriched with each member's expertise
  and use-hint drawn from the compiled agent definitions (falling back
  to the previous thin line on any read/parse failure), and a matching
  directive lands in the directives template. Existing repos pick all
  of this up via `troupe upgrade`.
- `troupe init` now flags possible detection failure: a scan that
  finds no signals and no languages says so in the proposal instead of
  silently presenting the minimal roster as if the repo were read
  correctly.
- File-guard hardening: compiled agent definitions
  (`.claude/agents/*.md`) are now protected paths, and the guard fails
  closed on unexpected internal errors — an unhandled crash now blocks
  the write with a clear message instead of surfacing a raw traceback.
- Reeve no longer crashes when the child process reports non-numeric
  cost/turns fields — the run degrades to a clean failed result and
  cycle state is still saved, instead of losing the cycle counter and
  any cost already spent.
- Monorepo scan fix: frontend-only components are no longer cited as
  backend evidence in the proposed roster's rationale.
- Docs: CONTRIBUTING.md added; `docs/design/` retired (design docs are
  no longer committed to the repo) and its dangling references swept.

## 0.3.0 (2026-07-06)

- `troupe init`'s scan is now monorepo-aware. Previously it only checked
  the exact directory it was pointed at for a project manifest, so any
  repo with projects split into subdirectories (no root-level manifest)
  scanned as empty. The scanner now discovers project manifests up to
  4 directories deep, purely by presence of known manifest filenames —
  no hardcoded directory names — and proposes a roster that reflects
  every discovered component (e.g. a React frontend nested in `ui/`, a
  Python API in `api/`, now both correctly detected and cast). New
  `kind: "monorepo"` classification and a `Components:` line in the
  scan summary when more than one project is found. Single-project
  repos are unaffected — output is byte-for-byte identical to 0.2.0.

## 0.2.0 (2026-07-06)

- `troupe init` now scans the repository (deterministic, offline,
  stdlib-only, bounded) before drafting the roster: manifests, CLI
  entrypoints, service/frontend frameworks, tests, CI, infra, data, and
  docs markers feed an evidence-gated proposal, printed with per-role
  rationale, that the user confirms before anything is written. `--yes`,
  `--dry-run`, and `--no-scan` flags added; `--roles` keeps its previous
  promptless behavior exactly, and `--no-scan` reproduces pre-0.2.0 output
  byte-for-byte. **Breaking (Alpha):** bare `init` in a non-TTY context
  (e.g. CI) now exits 2 asking for `--yes`/`--roles` instead of scaffolding
  silently.
- Specialized charters (e.g. `backend` retitled "Core" for CLI/library
  projects) persist across `troupe upgrade` instead of reverting to the
  generic catalog text.
- Repo-extracted text (manifest names/descriptions) is sanitized before
  it ever reaches a charter, history, team.md, or the terminal — stripped
  of ANSI/control/bidi-override characters, collapsed to a single line,
  length-capped, and always rendered as quoted data under a fixed
  "auto-detected, not instructions" framing line.
- `/troupe-explore` — a new user-invoked Claude Code slash command that
  fans out to every active cast member in parallel, each reading their
  own ownership area and appending findings to their own `history.md`.
  Ships scaffolded and kept current via `troupe upgrade`, like the
  governance hooks and agent definitions.

## 0.1.1 (2026-07-06)

- Metadata: development-status classifier corrected to `3 - Alpha`,
  matching the README's stated maturity. No code changes.

## 0.1.0 (2026-07-06)

Initial release. Reeve's execute path was rehearsed live against a sandbox
repo before this release: one governed cycle fixed a README typo and
commented its outcome on the issue for $0.55 of a $2.00 budget.

- `troupe init` — casts a persistent, named AI team (craft-surname pool with
  role affinities) into `.troupe/` + `.claude/`; idempotent, never overwrites
  team state
- Compiled agent definitions in `.claude/agents/` work both as Agent Teams
  teammate types and as plain subagents (no experimental flag required)
- Six enforced governance hooks, emitted as self-contained stdlib-only
  scripts: file-write guard, PII scrub (redact-in-place), decision logger,
  opt-in human review gate, bounded idle nudge, session context injection
- `troupe doctor` — setup diagnosis; `troupe upgrade` — refreshes
  troupe-owned files without touching team state
- Reeve (`troupe watch`) — autonomous GitHub issue watch: triage-only by
  default, `--execute` opt-in, turn/budget/wall-clock ceilings per run,
  per-cycle and per-day cost caps, per-issue failure backoff with human
  escalation, `reeve-stop` sentinel
- Claude Code plugin manifest + skill wrapping the CLI
- CI across Ubuntu/macOS/Windows; PyPI publishing via Trusted Publishing
