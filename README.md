# Troupe

**A persistent, governed AI team for Claude Code.**

Troupe gives you a named cast of AI specialists — lead, frontend, backend, tester — that live in your repo as files. They persist across sessions, share an architectural decision log, work under governance rules enforced by real Claude Code hooks (not prompt suggestions), and can optionally triage your GitHub issues overnight.

> ⚠️ Pre-alpha. Nothing to see here yet — the scaffolding is still going up.

## What Troupe adds on top of Claude Code's Agent Teams

Claude Code's experimental [Agent Teams](https://code.claude.com/docs/en/agent-teams) already handles orchestration: a team lead, parallel teammates, a shared task list, inter-agent messaging. Troupe deliberately builds none of that. Instead it fills the gaps that are file-shaped:

- **A persistent cast** — your team keeps its names, charters, and accumulated knowledge across sessions. Meet Wright (lead), Mason (backend), Webster (frontend), Sawyer (tester), Ward (security), Piper (DevOps).
- **Governance with teeth** — file-write guards, PII scrubbing, and reviewer lockout as real `PreToolUse`/`TaskCompleted` hooks that block, not ask nicely.
- **A shared brain** — `decisions.md` and `directives.md` accumulate architectural choices and permanent team rules, automatically.
- **Ralph** *(well, ours isn't called Ralph)* — an autonomous watch loop that polls GitHub issues and dispatches headless Claude Code runs while you sleep.

Works with Agent Teams when the flag is on; degrades gracefully to plain subagents when it's off.

## Quick start

```bash
uvx troupe init   # (coming soon)
```

## License

MIT — see [LICENSE](LICENSE).
