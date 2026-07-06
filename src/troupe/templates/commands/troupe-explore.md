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
