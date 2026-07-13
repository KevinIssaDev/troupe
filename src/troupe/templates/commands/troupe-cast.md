---
description: Add a role to the cast or retire a cast member, via the troupe CLI.
allowed-tools: Read, Bash
---

# /troupe-cast

Grow or retire the cast by running the `troupe cast` CLI — never by
editing `.troupe/casting-state.json` or `.claude/agents/*.md` directly.

## Steps

1. **Check for an empty roster first.** Read `.troupe/team.md`'s `## Cast`
   table. If it has zero rows, this is a bare repo with no team yet — that's
   `/troupe-setup`'s job, not this command's: it reads the repo and proposes
   a whole roster grounded in what it finds, instead of you naming roles one
   at a time. Say so and suggest running `/troupe-setup` instead. Only
   proceed here if the user explicitly says they still want to add just one
   role this way.

2. Work out from the request what's being asked:
   - Adding a role (e.g. "add a security specialist," "we need someone on
     docs") maps to `--add-role <role-id>`. Use a role id from the
     project's catalog if one clearly fits (lead, backend, frontend,
     tester, security, devops, docs, data, design); if the user names
     something that doesn't map to a known id, pass their word through
     as-is — `resolve_role()` synthesizes a generic charter for it, same
     as `--roles` does today.
   - If the request doesn't already name a role or a clear need, ask what
     role to add as a plain open-ended question — do not present the role
     catalog as a multiple-choice list. It has nine entries, above the
     four-option limit on choice-style questions, and the id doesn't need
     to be one of the nine anyway.
   - Retiring someone (e.g. "retire Webster," "we don't need a frontend
     person anymore") maps to `--retire <name>`, using the cast member's
     name as it appears in `.troupe/team.md`'s `## Cast` table.
   - Both can apply to one request ("swap Webster for a security
     specialist" is `--retire webster --add-role security`).
3. Run `troupe cast [--add-role ROLE]... [--retire NAME]... [--reason "..."]`
   via Bash from the project root. Pass `--reason` with a short summary of
   why, taken from the user's own words, so the decision log the CLI
   writes is meaningful rather than empty.
4. Report back what changed: any new cast member's name and role, any
   retired member's name, and confirm their `history.md` was left intact
   (retiring never deletes it).
5. If the command errors (unknown role, name not found, already retired),
   relay the CLI's error message plainly — do not try to work around it by
   editing state files yourself.

## Notes

- This command's whole job is running the CLI correctly. It never edits
  `.troupe/casting-state.json`, `.claude/agents/*.md`, or any charter or
  history file itself.
- `troupe cast` requires the `troupe` package to be installed and on PATH
  in this environment; if the Bash call fails with "command not found,"
  say so rather than guessing at an alternative.
