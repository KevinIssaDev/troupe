# Directives

> Standing rules for the troupe. Unlike `decisions.md` (a history), this file is current law: edit in place, keep it short, delete rules that no longer apply.
> If the user states a ground rule mid-session — a constraint to follow going forward ("never
> commit," "plans go in X") rather than a one-off choice with reasoning — add it here, not to
> `decisions.md`.

- Read `.troupe/decisions.md` before starting work; record team-relevant choices there.
- Never commit secrets, credentials, or personal data to the repository.
- Work stays inside your charter's ownership area; hand the rest back to the lead.
- The coordinating session (no charter) delegates by default: work in a cast member's ownership area goes to that member, not done inline.
- Adding or retiring a cast member is the lead's call: run `troupe cast --add-role <role>`
  or `troupe cast --retire <name>` (via Bash) — never hand-edit `casting-state.json`
  or `.claude/agents/*.md` directly.
- Keep `.troupe/focus.md` current — overwrite it (don't append) when the team's active focus changes.
- When you discover a reusable pattern or heuristic, distill it into `.troupe/wisdom.md` — not raw
  transcripts or per-task notes; those belong in your own `agents/<name>/history.md`.
