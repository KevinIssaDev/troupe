# Troupe

**A persistent, governed AI team for Claude Code.**

Troupe gives your repository a named cast of AI specialists — a lead, a backend dev, a frontend dev, a tester — that **live in your repo as files**. They keep their names, charters, and accumulated knowledge across sessions, share an append-only architectural decision log, work under governance rules enforced by real Claude Code hooks (not polite prompt suggestions), and can optionally triage your GitHub issues overnight.

> ⚠️ **Alpha software.** Interfaces may change between releases. Reeve (the autonomous watch) spends real money when you pass `--execute` — read [its safety model](#reeve--the-autonomous-issue-watch) first.

```
$ uvx troupe init
Project: your-project
Detected: ...
Proposed cast: ...
Cast this team? [y/N]: y

Cast:
  Wright     Lead
  Mason      Backend
  Webster    Frontend
  Sawyer     Tester
Created 24 file(s), left 0 untouched.
```

## Why Troupe when Agent Teams exists

Claude Code's experimental [Agent Teams](https://code.claude.com/docs/en/agent-teams) already does orchestration well: a team lead, parallel teammates with their own context windows, a shared task list, inter-agent messaging. **Troupe builds none of that.** It fills the gaps that are file-shaped — the things that vanish when the session ends:

| | Agent Teams (native) | Troupe adds |
|---|---|---|
| **Team identity** | Session-scoped; teams are named `session-…` and dissolve on exit | A persistent cast with names, charters, and per-member history, committed to the repo |
| **Rules & memory** | Task list persists per session, holds ephemeral work items | `decisions.md` (append-only decision log) + `directives.md` (standing rules), injected into every session |
| **Governance** | Permission modes and hook *capability* | Enforced policy content: file-write guard, PII scrub, reviewer lockout, bounded idle nudge — emitted as working hooks |
| **Unattended work** | — | Reeve: a schedulable issue watch with hard cost/turn/time ceilings |

Compared to its prior art, [Squad](https://github.com/bradygaster/squad) (which pioneered this model for GitHub Copilot CLI): Troupe is Python-native, targets Claude Code, and leans on Agent Teams for all orchestration instead of shipping its own coordinator. Compared to orchestrators like Gas Town or Multiclaude, Troupe doesn't compete on spawn mechanics at all — it's the persistence and governance layer underneath whatever does the orchestrating.

Works with the Agent Teams flag on (cast members become teammate types); degrades gracefully to plain subagents when it's off. Both paths use the same `.claude/agents/` definitions.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) (or pip), Claude Code. `gh` CLI only if you use Reeve.

```bash
cd your-project
uvx troupe init                       # scans the repo, proposes a tailored cast, confirms before writing
uvx troupe init --yes                 # accept the proposed cast without prompting (CI-friendly)
uvx troupe init --roles lead,backend,frontend,tester,security,devops,docs   # skip the proposal, cast exactly these
uvx troupe init --no-scan             # skip the scan entirely: default cast, generic charters
git add .troupe .claude && git commit -m "cast the troupe"
```

`init` scans the repo first — manifests, CLI entrypoints, frameworks, tests, CI, infra, docs markers — and proposes a cast with per-role rationale before writing anything (`--dry-run` previews without writing). In a non-interactive shell (CI, scripts), bare `init` exits 2 asking for `--yes` or `--roles` rather than scaffolding silently. The scan is monorepo-aware: a repo with no root manifest but several projects nested a few directories down (e.g. `api/`, `ui/`) is detected as `kind: monorepo`, and the proposal covers every discovered component.

Then open Claude Code in the project. The `SessionStart` hook injects the roster, standing rules, and recent decisions into every session automatically. Run `/troupe-explore` to have every active cast member read their own ownership area of the codebase and record findings in their own `history.md` — a deliberate, user-invoked deep pass beyond the scan's deterministic summary. Spawn cast members as subagents (or, with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, as teammates) by their agent type:

```
Spawn a teammate using the mason agent type to build the API endpoints,
and sawyer to write tests for them.
```

Check or repair a setup any time:

```bash
uvx troupe doctor      # diagnoses scaffold, hooks, wiring, environment
uvx troupe upgrade     # refreshes troupe-owned files; never touches team state
```

## What gets created

```
.troupe/
├── team.md              # roster
├── decisions.md         # append-only decision log (auto-fed by hook)
├── directives.md        # standing rules, edit in place
├── policy.json          # governance policy: protected paths, PII, gates
├── profile.json         # the scan's project profile (kind, languages, signals, components)
├── config.json · casting-state.json
└── agents/{name}/
    ├── charter.md       # role definition, seeded with what the scan found — yours to edit
    └── history.md       # accumulated knowledge — the agent appends
.claude/
├── settings.json        # hook wiring (merged non-destructively)
├── hooks/               # six self-contained governance scripts (stdlib-only)
├── commands/troupe-explore.md  # the /troupe-explore slash command
└── agents/{name}.md     # compiled definitions: teammate types AND subagents
```

Commit `.troupe/` and `.claude/`. Anyone who clones gets the team — same names, same knowledge, same rules.

### The cast

Names come from English occupational surnames, chosen so the etymology quietly maps to the role: **Wright** (master builder) leads, **Mason** (foundations) takes backend, **Webster** (weaver — of webs) takes frontend, **Sawyer** (cuts things open) tests, **Ward** (watchman) does security, **Piper** (keeps pipes flowing) does DevOps, **Page** does docs. A 24-name pool with role affinities backs larger casts; names are never reused within a project, even after a member retires.

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

`troupe upgrade` never touches team state (charters, histories, decisions, directives, casting) and never modifies policy keys you've edited — it only adds missing sections.

## Development

```bash
git clone https://github.com/KevinIssaDev/troupe && cd troupe
uv sync --dev
uv run pytest            # 150+ tests; gh and claude are stubbed throughout
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

CI runs the suite on Ubuntu, macOS, and Windows (cross-platform is a first-class concern — paths via `pathlib`, subprocess in list form, no shell strings). Releases publish to PyPI via Trusted Publishing on version tags. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow (branching, one-PR-per-change, the troupe cast you'll encounter in this repo).

## License

MIT — see [LICENSE](LICENSE). Squad (MIT, by [@bradygaster](https://github.com/bradygaster)) is gratefully acknowledged as prior art for the architecture and conventions; Troupe shares no code, name, or cast with it.
