# Changelog

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
