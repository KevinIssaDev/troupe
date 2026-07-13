# Troupe

**A persistent, governed AI team for Claude Code.**

Troupe gives your repository a named cast of AI specialists — a lead, a backend dev, a tester, whatever your codebase calls for. The cast lives in your repo as plain files: each member has a charter (what they own) and a history (what they've learned), and the team shares a decision log and standing rules. Commit the files and the team travels with the repo — same names, same knowledge, same rules, on every machine and for every collaborator.

Governance is enforced by real Claude Code hooks, not instructions an agent can ignore: protected files can't be overwritten, emails are scrubbed before they're written, and an optional review gate blocks task completion until a human signs off.

> ⚠️ **Alpha software.** Interfaces may change between releases. Reeve (the autonomous issue watch) spends real money when you pass `--execute` — read [its safety model](#reeve--the-autonomous-issue-watch) first.

## Install

```bash
uvx troupe init
```

That's it — no separate install step. `uvx` fetches the latest `troupe` from PyPI and runs it in one shot. (Prefer a persistent install? `uv tool install troupe` or `pip install troupe`, then run `troupe init`.)

## Getting started

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) (or pip), Claude Code. The `gh` CLI only if you use Reeve.

**1. Scaffold** (from your project root):

```bash
uvx troupe init
git add .troupe .claude && git commit -m "scaffold the troupe"
```

This creates the `.troupe/` team state, the governance hooks, and the slash commands. No cast members yet.

**2. Cast your team.** Open Claude Code in the project and run:

```
/troupe-setup
```

Claude reads your repo — manifests, entrypoints, directory structure, CI — and proposes a roster tailored to it, one specialist per area of the codebase:

```
🎯 Wright   — Architecture   cross-cutting design, review gate
🔧 Mason    — API            Flask backend, ODM, background jobs
⚛️ Webster  — UI             React/TS SPA, components
🧪 Fletcher — Quality        test suites across the stack
```

Nothing is written until you approve the lineup. Each member gets a charter grounded in what was actually read, and every roster change is logged to the team's decision log with its reasoning.

**3. Put them to work.** Just ask — work is routed to whoever owns that part of the codebase:

```
Hey team, build the API endpoints and test them.
```

Members run as subagents — or as parallel teammates, with Claude Code's [Agent Teams](https://code.claude.com/docs/en/agent-teams) flag on. You can also address anyone by name ("Mason, ...").

Every session starts with the roster, standing rules, and recent decisions already injected — you never re-explain who's who. Members read their own charter and history before working, stay inside their ownership area, and record what they learn when they finish.

**Optionally, seed their memory.** Run `/troupe-explore` to have every member read their own area of the codebase in parallel and write real findings into their history — so they start their first task already knowing the terrain.

## Slash commands

| Command | What it does |
|---|---|
| `/troupe-setup` | Propose and apply a repo-grounded cast and charters, with your confirmation first. Also re-tailors an existing roster as the codebase evolves. |
| `/troupe-cast` | Grow or retire the cast on request — "add a security specialist," "retire Webster." |
| `/troupe-explore` | Each member reads their own ownership area and records findings in their history. |

## What's in your repo

```
.troupe/
├── team.md              # the roster
├── decisions.md         # append-only decision log — why things are the way they are
├── directives.md        # standing rules, current law — edit in place
├── focus.md             # what the team is working on right now
├── wisdom.md            # distilled, reusable patterns the team has learned
├── policy.json          # governance policy: protected paths, PII rules, gates
├── config.json · casting-state.json
└── agents/{name}/
    ├── charter.md       # the member's mandate — yours to edit
    └── history.md       # the member's accumulated knowledge
.claude/
├── settings.json        # hook wiring (merged into your existing settings, non-destructively)
├── hooks/               # six governance scripts — self-contained, stdlib-only Python
├── commands/            # the three slash commands
└── agents/{name}.md     # compiled agent definitions (subagent and teammate types)
```

Everything is readable, diffable markdown and JSON. Charters, directives, and policy are yours to edit; generated files (`.claude/hooks/`, `.claude/agents/`) are refreshed by `troupe upgrade`.

### The cast

Names are English occupational surnames, picked so the etymology maps to the role: **Wright** (master builder) leads, **Mason** (foundations) takes backend, **Webster** (weaver — of webs) takes frontend, **Sawyer** (cuts things open) tests, **Ward** (watchman) does security, **Piper** (keeps pipes flowing) does DevOps, **Page** does docs. A 24-name pool backs larger casts, and a name is never reused within a project — even after its member retires.

## Governance

Six hooks are wired into Claude Code and fire on every session — including unattended ones:

| Hook | Event | What it enforces |
|---|---|---|
| File guard | `PreToolUse` | Blocks agent writes to protected paths: casting state, charters, the policy file itself, hooks, `.env*`, keys |
| PII scrub | `PreToolUse` | Redacts email addresses before content hits disk; allowlist for intentional ones |
| Decision log | `TaskCompleted` | Appends a structured entry to `decisions.md` for every completed task |
| Review gate | `TaskCompleted` | Opt-in: blocks completion until a human drops an approval marker — which is itself write-protected, so agents can't self-approve |
| Idle nudge | `TeammateIdle` | Sends idling teammates back for a final sweep, capped at 2 nudges per agent per session |
| Session context | `SessionStart` | Injects roster, directives, and recent decisions into every session |

Tune it all in `.troupe/policy.json` — patterns, allowlists, and toggles. The file guard protects the policy file from agents, so only you can loosen it.

## Reeve — the autonomous issue watch

A *reeve* was the manorial overseer: the one who made sure the estate's work actually got done. Reeve polls GitHub issues labeled `troupe` and, only when explicitly told, dispatches headless Claude Code sessions to work them.

```bash
uvx troupe watch --once               # one read-only triage cycle (cron-friendly)
uvx troupe watch                      # poll every 10 min, still read-only
uvx troupe watch --execute            # actually work issues (costs money)
```

**Safety model, in order of the walls you'd hit:**

- **Triage-only by default.** No `--execute` → no writes, no agent runs, no cost. Ever.
- **Reeve itself never writes to GitHub.** Comments happen inside the governed Claude session, under its permission rules (`acceptEdits` plus a narrow `gh`/`git`-read allowlist). `--skip-permissions` exists but is refused without `--execute`.
- **Governance stays on during unattended work.** Runs pass `--settings` explicitly, so the file guard and PII scrub fire exactly when nobody's watching.
- **Three independent ceilings per run:** `--max-turns` (30), `--max-budget-usd`, and `--timeout-minutes` (30 — a hard wall-clock kill for hangs).
- **Two accumulating ceilings:** `--max-cost-per-cycle` ($2) and `--max-cost-per-day` ($10).
- **Per-issue backoff:** a failing issue cools down 2 cycles per failure and escalates to a human after 3 failures (`--reset-backoff` clears the ledger).
- **Clean shutdown:** `touch .troupe/reeve-stop` — Reeve finishes the current cycle and exits. The sentinel is write-protected from agents; only you can stop the overseer.

Run it from cron, a systemd timer, or Task Scheduler with `--once`. **Point it at a throwaway repo first.**

## CLI reference

| Command | What it does |
|---|---|
| `troupe init` | Scaffold `.troupe/` and `.claude/`. Idempotent — re-running fills gaps, never overwrites team state. |
| `troupe doctor` | Diagnose a setup: missing files, stale or unwired hooks, policy drift, environment. |
| `troupe upgrade` | Refresh troupe-owned files from the installed version. Never touches team state or policy keys you've edited. |
| `troupe cast --add-role ID / --retire NAME` | Grow or retire the cast. What `/troupe-cast` and `/troupe-setup` run under the hood; also the sanctioned way to script roster changes. |
| `troupe charter NAME --title/--expertise/--ownership/--use-hint` | Edit a member's mandate through structured fields. |
| `troupe watch` | Reeve's polling loop (see above). |

## How Troupe relates to Agent Teams

Claude Code's [Agent Teams](https://code.claude.com/docs/en/agent-teams) handles orchestration — parallel teammates, shared task lists, inter-agent messaging. Troupe handles what evaporates when the session ends:

| | Agent Teams (native) | Troupe adds |
|---|---|---|
| **Team identity** | Session-scoped; teams dissolve on exit | A persistent cast with names, charters, and per-member history, committed to the repo |
| **Rules & memory** | Task list holds ephemeral work items | Decision log, standing rules, current focus, and distilled patterns — injected into every session |
| **Governance** | Permission modes and hook *capability* | Enforced policy content: file guard, PII scrub, review gate, bounded idle nudge |
| **Unattended work** | — | Reeve, with hard cost/turn/time ceilings |

Troupe works with the Agent Teams flag on (cast members become teammate types) and degrades gracefully to plain subagents when it's off — both paths use the same `.claude/agents/` definitions.

## Upgrading

```bash
uv tool upgrade troupe   # or: pip install -U troupe
uvx troupe upgrade       # refresh hooks, agent definitions, missing policy sections
```

## Development

```bash
git clone https://github.com/KevinIssaDev/troupe && cd troupe
uv sync --dev
uv run pytest            # gh and claude are stubbed throughout — no network, no cost
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

CI runs the suite on Ubuntu, macOS, and Windows. Releases publish to PyPI via Trusted Publishing on version tags. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

## License

MIT — see [LICENSE](LICENSE). [Squad](https://github.com/bradygaster/squad) (MIT, by [@bradygaster](https://github.com/bradygaster)) is gratefully acknowledged as prior art for the architecture and conventions; Troupe shares no code, name, or cast with it.
