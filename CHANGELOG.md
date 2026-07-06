# Changelog

## Unreleased (0.1.0)

Initial release.

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
