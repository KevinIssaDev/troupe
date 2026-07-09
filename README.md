# Troupe

**A persistent, governed AI team for Claude Code.**

Troupe gives your repository a named cast of AI specialists — a lead, a backend dev, a frontend dev, a tester — that **live in your repo as files**. They keep their names, charters, and accumulated knowledge across sessions, share an append-only decision log and a standing-rules file, work under governance rules enforced by real Claude Code hooks (not polite prompt suggestions), and can optionally triage your GitHub issues overnight.

> ⚠️ **Alpha software.** Interfaces may change between releases. Reeve (the autonomous watch) spends real money when you pass `--execute` — read [its safety model](#reeve--the-autonomous-issue-watch) first.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) (or pip), Claude Code. `gh` CLI only if you use Reeve.

```bash
cd your-project
uvx troupe init                       # scaffolds .troupe/ and .claude/ — casts nobody yet
git add .troupe .claude && git commit -m "scaffold the troupe"
```

`init` unconditionally scaffolds governance — hooks, settings, an empty roster — and nothing else. There's no scan and no cast yet on purpose: casting a team well means actually reading the repo, and that's a job for a live Claude Code session, not a CLI heuristic.

Open Claude Code in the project and run **`/troupe-setup`**. It reads the repo (manifests, entrypoints, directory structure, CI config — a bounded ~25-file pass), proposes a roster with a rationale for each role, and waits for your confirmation before casting anyone via `troupe cast`/`troupe charter`. This works identically whether the roster is empty (first cast) or you're re-tailoring an existing one.

```
You: /troupe-setup

Claude: Proposed cast for a Flask API + React SPA:
  🎯 Wright  — Architecture   cross-cutting design, review gate
  🔧 Mason   — API            Flask backend, ODM, background jobs
  ⚛️ Webster — UI             React/TS SPA, components
  🧪 Fletcher — Quality       test suites across the stack
Cast this team? [waits for you to confirm]
```

From then on, the `SessionStart` hook injects the roster, standing rules, and recent decisions into every session automatically. Spawn cast members as subagents (or, with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, as teammates) by their agent type:

```
Spawn a teammate using the mason agent type to build the API endpoints,
and fletcher to write tests for them.
```

Run `/troupe-explore` any time to have every active cast member read their own ownership area and record findings in their own `history.md` — a deliberate, user-invoked deep pass beyond what `/troupe-setup`'s bounded scan covers.

Check or repair a setup any time:

```bash
uvx troupe doctor      # diagnoses scaffold, hooks, wiring, environment
uvx troupe upgrade     # refreshes troupe-owned files; never touches team state
```

## Commands

| Command | What it does |
|---|---|
| `troupe init [path]` | Scaffold `.troupe/` + `.claude/`. Casts nobody. Idempotent — safe to re-run, never overwrites existing team state. |
| `troupe doctor [path]` | Diagnose the setup: missing scaffold files, stale/unwired hooks, policy drift, environment. Exit 1 on any failure. |
| `troupe upgrade [path]` | Refresh troupe-owned files (hook scripts, agent definitions, missing policy sections) from the installed version's templates. Never touches team state. |
| `troupe cast [--add-role ID]... [--retire NAME]... [--reason "..."]` | Grow or retire the cast directly. Explicit input, no scan, no confirm prompt — this is what `/troupe-cast` runs under the hood. |
| `troupe charter NAME [--title] [--expertise] [--ownership]... [--use-hint] [--reason]` | Edit a cast member's mandate through structured fields, applied immediately. What `/troupe-setup`'s charter edits run under the hood. |
| `troupe watch [--execute]` | Reeve's polling loop over GitHub issues. See [below](#reeve--the-autonomous-issue-watch). |

Most of these you'll never type yourself — the Claude Code slash commands below call `cast`/`charter` for you with the right flags and log a decision entry automatically. They're documented here because `troupe cast`/`troupe charter` are also the *only* sanctioned way to hand-edit the roster if you're scripting something outside Claude Code.

## Slash commands (inside Claude Code)

| Command | What it does |
|---|---|
| `/troupe-setup` | Propose and apply a repo-grounded cast and charters, with your confirmation first. Same flow for an empty roster or re-tailoring an existing one. |
| `/troupe-cast` | Grow or retire the cast for an explicit request ("add a security specialist," "retire Webster") — no repo scan. |
| `/troupe-explore` | Have every active cast member read their own ownership area and record findings in their `history.md`. |

None of these ever hand-edit `.troupe/casting-state.json` or `.claude/agents/*.md` directly — they always go through the `troupe cast`/`troupe charter` CLI, so every roster change is validated and logged to `decisions.md` the same way.

## Why Troupe when Agent Teams exists

Claude Code's experimental [Agent Teams](https://code.claude.com/docs/en/agent-teams) already does orchestration well: a team lead, parallel teammates with their own context windows, a shared task list, inter-agent messaging. **Troupe builds none of that.** It fills the gaps that are file-shaped — the things that vanish when the session ends:

| | Agent Teams (native) | Troupe adds |
|---|---|---|
| **Team identity** | Session-scoped; teams are named `session-…` and dissolve on exit | A persistent cast with names, charters, and per-member history, committed to the repo |
| **Rules & memory** | Task list persists per session, holds ephemeral work items | `decisions.md` (history) + `directives.md` (standing rules) + `focus.md` (what's active now) + `wisdom.md` (distilled patterns), injected into every session |
| **Governance** | Permission modes and hook *capability* | Enforced policy content: file-write guard, PII scrub, reviewer lockout, bounded idle nudge — emitted as working hooks |
| **Unattended work** | — | Reeve: a schedulable issue watch with hard cost/turn/time ceilings |

Compared to its prior art, [Squad](https://github.com/bradygaster/squad) (which pioneered this model for GitHub Copilot CLI): Troupe is Python-native, targets Claude Code, and leans on Agent Teams for all orchestration instead of shipping its own coordinator. Compared to orchestrators like Gas Town or Multiclaude, Troupe doesn't compete on spawn mechanics at all — it's the persistence and governance layer underneath whatever does the orchestrating.

Works with the Agent Teams flag on (cast members become teammate types); degrades gracefully to plain subagents when it's off. Both paths use the same `.claude/agents/` definitions.

## What gets created

```
.troupe/
├── team.md              # roster
├── decisions.md         # append-only decision log (auto-fed by hook)
├── directives.md        # standing rules, edit in place
├── focus.md              # what the team is working on right now (overwrite in place)
├── wisdom.md             # distilled, reusable patterns (append-only)
├── policy.json           # governance policy: protected paths, PII, gates
├── config.json · casting-state.json
└── agents/{name}/
    ├── charter.md       # role definition — set by /troupe-setup, yours to edit after
    └── history.md       # accumulated knowledge — the agent appends
.claude/
├── settings.json        # hook wiring (merged non-destructively)
├── hooks/               # six self-contained governance scripts (stdlib-only)
├── commands/             # /troupe-setup, /troupe-cast, /troupe-explore
└── agents/{name}.md     # compiled definitions: teammate types AND subagents
```

Commit `.troupe/` and `.claude/`. Anyone who clones gets the team — same names, same knowledge, same rules.

### The cast

Names come from English occupational surnames, chosen so the etymology quietly maps to the role: **Wright** (master builder) leads, **Mason** (foundations) takes backend, **Webster** (weaver — of webs) takes frontend, **Sawyer** (cuts things open) tests, **Ward** (watchman) does security, **Piper** (keeps pipes flowing) does DevOps, **Page** does docs. A 24-name pool with role affinities backs larger casts; names are never reused within a project, even after a member retires.

`/troupe-setup` renders a proposed roster with a fixed emoji per role — 🎯 lead, 🔧 backend, ⚛️ frontend, 🧪 tester, 🛡️ security, 🔄 devops, 📋 docs, 📊 data, 🎨 design — so the lineup is easy to scan before you confirm it.

## Governance — enforced, not suggested

`troupe init` emits six hook scripts into `.claude/hooks/` — self-contained, stdlib-only Python, so they run on any machine with no troupe install on the per-tool-call hot path:

| Hook | Event | What it enforces |
|---|---|---|
| File guard | `PreToolUse` | Blocks agent writes to protected paths (casting state, charters, policy itself, hooks, `.env*`, keys) per `policy.json` |
| PII scrub | `PreToolUse` | Redacts email addresses *in place* before content is written; allowlist for intentional ones |
| Decision log | `TaskCompleted` | Appends a structured entry to `decisions.md` for every completed task |
| Review gate | `TaskCompleted` | Opt-in: blocks completion until a human drops a marker in `.troupe/approvals/` — which is itself write-protected, so agents can't self-approve |
| Idle nudge | `TeammateIdle` | Sends idling teammates back for a final sweep — strictly bounded (2 nudges/agent/session), so no infinite keep-alive |
| Session context | `SessionStart` | Injects roster + directives + recent decisions into every session, and tells the coordinating session to delegate to the owning cast member by default |

Policy lives in `.troupe/policy.json` — patterns, allowlists, and toggles are yours to edit; the file guard protects the file itself from agents.

## Reeve — the autonomous issue watch

A *reeve* was the manorial overseer: the one who made sure the estate's work actually got done. Reeve polls GitHub issues labeled `troupe` and, only when explicitly told, dispatches headless Claude Code sessions to work them.

```bash
uvx troupe watch --once               # one read-only triage cycle (cron-friendly)
uvx troupe watch                      # poll every 10 min, still read-only
uvx troupe watch --execute            # actually work issues (costs money)
```

**Safety model, in order of the walls you'd hit:**

- **Triage-only by default.** No `--execute` → no writes, no agent runs, no cost. Ever.
- **Reeve itself never writes to GitHub.** Comments happen inside the governed Claude session, under its permission rules (`acceptEdits` + a narrow `gh`/`git`-read allowlist). `--skip-permissions` exists but is refused without `--execute`.
- **Governance stays on during unattended work.** Runs are non-bare and pass `--settings` explicitly, so the file guard and PII scrub fire exactly when nobody's watching.
- **Three independent ceilings per run**: `--max-turns` (30), `--max-budget-usd` (native cost cap), and `--timeout-minutes` (30, hard wall-clock kill for hangs).
- **Two accumulating ceilings**: `--max-cost-per-cycle` ($2) and `--max-cost-per-day` ($10), tracked from the JSON output's `total_cost_usd`.
- **Per-issue backoff**: a failing issue cools down 2 cycles per failure and escalates to humans after 3 failures (`--reset-backoff` clears the ledger).
- **Clean shutdown**: `touch .troupe/reeve-stop` — Reeve finishes the cycle and exits. The sentinel is write-protected from agents; only you can stop the overseer.

Run it from cron, a systemd timer, or Task Scheduler with `--once`. **Point it at a throwaway repo first.**

## Upgrading

```bash
uv tool upgrade troupe   # or: pip install -U troupe
uvx troupe upgrade       # refresh hook scripts, agent definitions, policy sections
```

`troupe upgrade` never touches team state (charters, histories, decisions, directives, focus, wisdom, casting) and never modifies policy keys you've edited — it only adds missing sections.

## Development

```bash
git clone https://github.com/KevinIssaDev/troupe && cd troupe
uv sync --dev
uv run pytest            # 170+ tests; gh and claude are stubbed throughout
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

CI runs the suite on Ubuntu, macOS, and Windows (cross-platform is a first-class concern — paths via `pathlib`, subprocess in list form, no shell strings). Releases publish to PyPI via Trusted Publishing on version tags. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow (branching, one-PR-per-change, the troupe cast you'll encounter in this repo).

## License

MIT — see [LICENSE](LICENSE). Squad (MIT, by [@bradygaster](https://github.com/bradygaster)) is gratefully acknowledged as prior art for the architecture and conventions; Troupe shares no code, name, or cast with it.
