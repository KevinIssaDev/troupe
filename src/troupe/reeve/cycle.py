"""One Reeve cycle: poll → prioritize → (triage report | execute one issue)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from troupe.reeve import context as context_mod
from troupe.reeve import poller, runner
from troupe.reeve.state import StateStore


@dataclass(frozen=True)
class CycleOptions:
    label: str = "troupe"
    limit: int = 20
    execute: bool = False
    skip_permissions: bool = False
    max_turns: int = 30
    max_cost_per_cycle: float = 2.0
    max_cost_per_day: float = 10.0
    timeout_minutes: float = 30.0
    claude_cmd: str = "claude"


@dataclass
class CycleReport:
    cycle: int
    lines: list[str] = field(default_factory=list)
    executed_issue: int | None = None
    cost_usd: float = 0.0
    ok: bool = True

    def add(self, line: str) -> None:
        self.lines.append(line)


def run_cycle(
    root: Path,
    options: CycleOptions,
    *,
    fetch=poller.fetch_issues,
    run_claude=runner.run_claude,
) -> CycleReport:
    root = root.resolve()
    troupe_dir = root / ".troupe"
    state = StateStore(troupe_dir)
    report = CycleReport(cycle=state.begin_cycle())

    try:
        issues = poller.prioritize(fetch(options.label, options.limit))
    except poller.PollError as exc:
        report.ok = False
        report.add(f"poll failed: {exc}")
        state.save()
        return report

    if not issues:
        report.add(f"board clear: no open issues labeled '{options.label}'")
        state.save()
        return report

    for issue in issues:
        verdict = state.eligibility(issue.number)
        marker = "" if verdict.eligible else f"  [skipped: {verdict.reason}]"
        report.add(f"#{issue.number} P{issue.priority} {issue.title}{marker}")

    if not options.execute:
        report.add("triage-only mode: no writes, no agent runs (pass --execute to work issues)")
        state.save()
        return report

    day_remaining = options.max_cost_per_day - state.daily_cost()
    if day_remaining <= 0:
        report.add(
            f"daily cost cap reached (${state.daily_cost():.2f} of "
            f"${options.max_cost_per_day:.2f}) - not executing until tomorrow"
        )
        state.save()
        return report
    budget = round(min(options.max_cost_per_cycle, day_remaining), 2)

    target = next((issue for issue in issues if state.eligibility(issue.number).eligible), None)
    if target is None:
        report.add("no eligible issues: all are cooling down or escalated")
        escalated = state.escalated()
        if escalated:
            report.add(f"escalated (need a human): {', '.join(f'#{n}' for n in escalated)}")
        state.save()
        return report

    report.add(f"executing #{target.number} (budget ${budget:.2f}, max {options.max_turns} turns)")
    work_context = context_mod.build_context(target, issues, troupe_dir, options.execute)
    result = run_claude(
        root,
        work_context,
        execute=options.execute,
        skip_permissions=options.skip_permissions,
        max_turns=options.max_turns,
        max_budget_usd=budget,
        timeout_minutes=options.timeout_minutes,
        claude_cmd=options.claude_cmd,
    )

    state.record_cost(result.cost_usd)
    report.cost_usd = result.cost_usd
    report.executed_issue = target.number

    if result.ok:
        state.record_success(target.number)
        report.add(
            f"#{target.number} run finished (${result.cost_usd:.2f}, {result.num_turns} turns)"
        )
    else:
        state.record_failure(target.number)
        report.ok = False
        verdict = state.eligibility(target.number)
        report.add(f"#{target.number} run failed: {result.error}")
        report.add(f"#{target.number} backoff: {verdict.reason}")

    report.add(f"daily spend: ${state.daily_cost():.2f} of ${options.max_cost_per_day:.2f}")
    state.save()
    return report
