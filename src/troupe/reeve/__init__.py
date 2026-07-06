"""Reeve — the troupe's autonomous watch loop.

A reeve was the manorial overseer: the one who made sure the estate's work
actually got done. This Reeve polls GitHub issues, prioritizes them, and —
only when explicitly told to execute — dispatches headless Claude Code
sessions to work them.

Architecture decisions (recorded 2026-07-06):

* **Governance stays active.** Headless runs are non-bare AND pass
  `--settings <root>/.claude/settings.json` explicitly, so the file guard,
  PII scrub, and decision logger fire during unattended work — which is when
  they matter most — and keep firing when `--bare` becomes the default for
  `claude -p`. The accepted trade-off is nondeterminism from user-level
  `~/.claude` configuration.
* **Reeve itself never writes to GitHub.** All comments/labels happen inside
  the governed Claude session, under its permission rules. The watcher
  process is read-only by construction.
* **Costs are capped independently of failure backoff.** Per call:
  `--max-turns` + native `--max-budget-usd`. Accumulated: per-cycle and
  per-day ceilings tracked from `total_cost_usd` in the JSON output.
* **One issue per cycle.** Reeve deterministically picks the top eligible
  issue (rather than letting the agent choose from the board) so failures
  attribute cleanly to an issue and backoff tiers work. The full board is
  still included in the work context for awareness.
"""
