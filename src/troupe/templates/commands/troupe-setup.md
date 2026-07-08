---
description: Propose and apply a repo-grounded cast and set of charters, via the troupe CLI, with your confirmation first.
allowed-tools: Read, Glob, Grep, Bash
---

# /troupe-setup

Cast a team (or re-tailor an existing one) grounded in a real read of this
repository, then apply the result with `troupe cast`/`troupe charter` — never
by hand-editing `.troupe/casting-state.json`, `.claude/agents/*.md`, or any
charter file directly. Both commands apply immediately (no staging, no
approval step) — a human is watching this conversation before any of it
runs, exactly like `/troupe-cast`.

This is the same flow whether the roster is empty (first cast after a bare
`troupe init`) or already has members you're revising — there is no separate
"first cast" mode.

## Steps

1. **Read the current state.** Read `.troupe/team.md`'s `## Cast` table (may
   be empty — that's normal right after `troupe init`) and, for each active
   member listed, their `.troupe/agents/<slug>/charter.md`. This tells you
   who's already on the roster and what their mandate currently says.

2. **Read the repo, bounded.** Do a bounded live read of the codebase — about
   25 file reads. Prioritize manifests, entrypoints, and directory listings
   before deep code: `pyproject.toml`/`package.json`/`go.mod`/etc., CI
   config, top-level directory structure, README, and a handful of the most
   central source files. The goal is enough signal to draw ownership
   boundaries, not an audit — deep reading of any one area is
   `/troupe-explore`'s job, and you should suggest running it after this
   command finishes. Do not exceed the ~25-read budget; if the repo is large
   or a monorepo, prefer breadth (one or two files per component) over depth
   in any single area.

3. **Propose a target roster.** Using the catalog role ids — lead, backend,
   frontend, tester, security, devops, docs, data, design — or a synthesized
   id for something that doesn't fit (e.g. `mobile`), work out who should be
   on the team: keep existing members whose mandate still fits, retitle or
   re-scope members whose ownership has drifted from what you actually read,
   add new members for uncovered areas, and retire members whose area no
   longer exists or is redundant. For every member in the target roster,
   draft concrete charter fields grounded in what you actually read this
   pass:
   - `--title` — short role title (e.g. "Core", "API").
   - `--expertise` — one line.
   - `--ownership` — repeatable, concrete paths/areas (e.g. `src/api/`, not
     "the backend"), including explicit boundary handoffs to other members
     where two areas are adjacent (e.g. "src/api/ — hands off to Frontend at
     the OpenAPI contract in src/api/schema.py").
   - `--use-hint` — when to reach for this member.

   Do not put exploit history, incident notes, or other tribal knowledge
   into charter fields — charters are a structured, present-tense mandate.
   That kind of narrative belongs in the member's `history.md`, written by
   `/troupe-explore` or by the member themselves, never here.

4. **Present the full plan and confirm.** Show the user the complete target
   state in this conversation — every keep/retitle/add/retire, and every
   charter field you intend to set — before running anything. If any part of
   the plan wasn't explicitly requested by the user (e.g. you're proposing
   to retire someone or change ownership boundaries on your own initiative),
   say so plainly and ask first. Wait for explicit confirmation before step 5.

5. **Execute.** Once confirmed, apply directly — no further staging or
   approval step:
   - Roster changes first, batched into a single `troupe cast` invocation:
     one call with `troupe cast --add-role <role>` repeated for every new
     member and `--retire <name>` repeated for every removal, plus one
     `--reason` summarizing the whole roster change, run via Bash from the
     project root. `--add-role`/`--retire` are repeatable flags on one
     invocation — never issue a separate `troupe cast` call per member; one
     invocation is one atomic roster change and logs exactly one decision
     entry. Skip this call entirely if the plan has no roster changes
     (charter-only edits).
   - For each member whose charter needs setting or changing: `troupe
     charter <name> --title "..." --expertise "..." --ownership "..."
     [--ownership "..." ...] --use-hint "..." --reason "..."`, one
     invocation per member. Pass `--reason` with a short summary in the
     user's own words so the decision log entry is meaningful.
   - If a command errors, relay the CLI's error message plainly — do not
     work around it by editing state files yourself.

6. **Report.** Summarize what changed: who was cast, retitled, or retired,
   and a one-line summary of each new/changed mandate. Suggest running
   `/troupe-explore` next so each member's `history.md` gets seeded with
   real findings from their own ownership area.

## Notes

- This command's whole job is proposing and applying roster/charter changes
  correctly. It never edits `.troupe/casting-state.json`, `.claude/agents/*.md`,
  or any charter/history file itself.
- `troupe cast`/`troupe charter` require the `troupe` package to be installed
  and on PATH in this environment; if a Bash call fails with "command not
  found," say so rather than guessing at an alternative.
