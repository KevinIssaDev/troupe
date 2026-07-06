---
description: Set up or maintain a Troupe AI team in this repository. Use when the user asks to create a persistent AI team, cast agents, check or repair a troupe (doctor/upgrade), or run the Reeve issue watch.
---

# Troupe

Troupe gives a repository a persistent, named AI team: a cast of specialists
(Wright the lead, Mason the backend, Webster the frontend, ...) whose
charters, shared decision log, and governance rules live in `.troupe/`, with
compiled agent definitions in `.claude/agents/` and enforced governance hooks
in `.claude/hooks/`.

All commands run via Bash. Prefer `uvx troupe ...` (zero install); if uvx is
unavailable, `pip install troupe` then `troupe ...`.

## Commands

- `uvx troupe init` — scaffold the team (default cast: lead, backend,
  frontend, tester). Add roles with `--roles lead,backend,frontend,tester,security,devops,docs`.
  Idempotent: re-running fills gaps and casts new roles, never overwrites
  team state.
- `uvx troupe doctor` — diagnose the setup. Run this first when something
  seems wrong.
- `uvx troupe upgrade` — refresh troupe-owned files (hook scripts, agent
  definitions, missing policy sections). Never touches team state.
- `uvx troupe watch --once` — one read-only triage cycle over GitHub issues
  labeled `troupe`. Adding `--execute` dispatches real agent runs and costs
  money: confirm with the user before ever passing `--execute`, and never
  pass `--skip-permissions` unless the user explicitly asks for it.

## Rules

- After `init`, tell the user to commit `.troupe/` and `.claude/` so the
  team travels with the repo.
- Never hand-edit `.claude/hooks/*` or weaken `.troupe/policy.json` —
  governance files are enforced by hooks and owned by `troupe upgrade`.
- Team knowledge belongs in `.troupe/decisions.md` (append-only decision
  log) and `.troupe/directives.md` (standing rules, edit in place).
- To stop a running watch: create the file `.troupe/reeve-stop`.
