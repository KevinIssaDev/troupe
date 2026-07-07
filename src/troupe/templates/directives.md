# Directives

> Standing rules for the troupe. Unlike `decisions.md` (a history), this file is current law: edit in place, keep it short, delete rules that no longer apply.

- Read `.troupe/decisions.md` before starting work; record team-relevant choices there.
- Never commit secrets, credentials, or personal data to the repository.
- Work stays inside your charter's ownership area; hand the rest back to the lead.
- Adding or retiring a cast member is the lead's call: run `troupe cast --add-role <role>`
  or `troupe cast --retire <name>` (via Bash) — never hand-edit `casting-state.json`
  or `.claude/agents/*.md` directly.
