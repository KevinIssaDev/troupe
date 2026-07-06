"""Reeve tests — all external commands (gh, claude) are stubbed; nothing
here talks to GitHub or the Claude API."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from troupe.cli import app
from troupe.reeve.context import build_context
from troupe.reeve.cycle import CycleOptions, run_cycle
from troupe.reeve.poller import Issue, PollError, fetch_issues, prioritize
from troupe.reeve.runner import RunResult, build_argv, run_claude
from troupe.reeve.state import StateStore

runner_cli = CliRunner()


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── poller ───────────────────────────────────────────────────────────


def gh_payload() -> str:
    return json.dumps(
        [
            {
                "number": 7,
                "title": "docs typo",
                "labels": [{"name": "p3"}],
                "url": "u7",
                "body": "",
            },
            {
                "number": 3,
                "title": "crash on login",
                "labels": [{"name": "P0"}],
                "url": "u3",
                "body": "boom",
            },
            {"number": 5, "title": "add caching", "labels": [], "url": "u5", "body": ""},
            {
                "number": 2,
                "title": "slow query",
                "labels": [{"name": "priority:high"}],
                "url": "u2",
                "body": "",
            },
        ]
    )


def test_fetch_and_prioritize_orders_by_urgency_then_age() -> None:
    issues = fetch_issues(
        "troupe", 20, Path(), run=lambda argv, cwd: completed(stdout=gh_payload())
    )
    ordered = [issue.number for issue in prioritize(issues)]
    assert ordered == [3, 2, 5, 7]  # P0, high, unlabeled, p3


def test_fetch_passes_label_and_limit() -> None:
    seen: list[list[str]] = []

    def fake(argv, cwd):
        seen.append(list(argv))
        return completed(stdout="[]")

    fetch_issues("mylabel", 5, Path(), run=fake)
    argv = seen[0]
    assert "--label" in argv and argv[argv.index("--label") + 1] == "mylabel"
    assert "--limit" in argv and argv[argv.index("--limit") + 1] == "5"


def test_fetch_raises_on_gh_failure() -> None:
    with pytest.raises(PollError, match="exit 1"):
        fetch_issues(
            "troupe", 20, Path(), run=lambda argv, cwd: completed(returncode=1, stderr="auth")
        )


def test_fetch_runs_gh_in_the_watched_project(tmp_path: Path) -> None:
    seen: list[Path] = []

    def fake(argv, cwd):
        seen.append(cwd)
        return completed(stdout="[]")

    fetch_issues("troupe", 5, tmp_path, run=fake)
    assert seen == [tmp_path]


def test_run_claude_runs_in_project_root(tmp_path: Path) -> None:
    seen: list[Path] = []

    def fake(argv, stdin_text, timeout, cwd):
        seen.append(cwd)
        return completed(stdout=json.dumps({"result": "ok", "total_cost_usd": 0}))

    run_claude(
        tmp_path,
        "ctx",
        execute=True,
        skip_permissions=False,
        max_turns=30,
        max_budget_usd=2.0,
        run=fake,
    )
    assert seen == [tmp_path]


# ── state / backoff ──────────────────────────────────────────────────


def test_backoff_tiers(project: Path) -> None:
    state = StateStore(project / ".troupe")
    state.begin_cycle()  # cycle 1
    assert state.eligibility(42).eligible

    state.record_failure(42)  # cooldown until cycle 3
    assert not state.eligibility(42).eligible
    state.begin_cycle()  # 2
    assert not state.eligibility(42).eligible
    state.begin_cycle()  # 3
    assert state.eligibility(42).eligible

    state.record_failure(42)  # 2 failures -> cooldown until 7
    state.record_failure(42)  # 3 failures -> escalated
    for _ in range(10):
        state.begin_cycle()
    verdict = state.eligibility(42)
    assert not verdict.eligible
    assert "escalated" in verdict.reason
    assert state.escalated() == [42]

    state.reset_backoff()
    assert state.eligibility(42).eligible


def test_success_clears_failures(project: Path) -> None:
    state = StateStore(project / ".troupe")
    state.begin_cycle()
    state.record_failure(9)
    state.record_success(9)
    assert state.eligibility(9).eligible
    assert state.eligibility(9).reason == "no prior failures"


def test_state_persists_and_costs_accumulate(project: Path) -> None:
    troupe_dir = project / ".troupe"
    state = StateStore(troupe_dir)
    state.begin_cycle()
    state.record_cost(1.25)
    state.record_cost(0.5)
    state.save()

    reloaded = StateStore(troupe_dir)
    assert reloaded.daily_cost() == pytest.approx(1.75)
    assert reloaded.cycle == 1
    assert (troupe_dir / ".runtime" / ".gitignore").exists()


# ── context ──────────────────────────────────────────────────────────


def test_context_contains_target_board_rules_and_team_memory(project: Path) -> None:
    troupe_dir = project / ".troupe"
    with (troupe_dir / "decisions.md").open("a", encoding="utf-8") as f:
        f.write("\n### 2026-07-06: Use sqlite\n**By:** Wright\n")
    target = Issue(number=3, title="crash on login", labels=("P0",), url="u3", body="stack trace")
    board = [target, Issue(number=7, title="docs typo")]

    text = build_context(target, board, troupe_dir, execute=True)

    assert "issue #3 - crash on login" in text
    assert "stack trace" in text
    assert "#7 docs typo" in text
    assert "do NOT work these" in text
    assert "Standing team rules" in text
    assert "Use sqlite" in text
    assert "gh issue comment 3" in text
    assert "Do NOT close the issue" in text


def test_context_omits_comment_instruction_outside_execute(project: Path) -> None:
    target = Issue(number=3, title="x")
    text = build_context(target, [target], project / ".troupe", execute=False)
    assert "gh issue comment" not in text


# ── runner ───────────────────────────────────────────────────────────


def test_argv_is_non_bare_with_explicit_settings(tmp_path: Path) -> None:
    argv = build_argv(
        tmp_path, execute=True, skip_permissions=False, max_turns=30, max_budget_usd=2.0
    )
    assert "--bare" not in argv
    assert "--settings" in argv
    assert str(tmp_path / ".claude" / "settings.json") in argv
    assert argv[argv.index("--max-turns") + 1] == "30"
    assert argv[argv.index("--max-budget-usd") + 1] == "2.00"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in argv
    allowed = argv[argv.index("--allowedTools") + 1]
    assert "Bash(gh issue comment *)" in allowed
    assert "Bash(rm" not in allowed


def test_argv_skip_permissions_replaces_allowlist(tmp_path: Path) -> None:
    argv = build_argv(
        tmp_path, execute=True, skip_permissions=True, max_turns=10, max_budget_usd=1.0
    )
    assert "--dangerously-skip-permissions" in argv
    assert "--allowedTools" not in argv


def test_run_claude_parses_success_json(tmp_path: Path) -> None:
    payload = json.dumps(
        {"result": "done", "total_cost_usd": 0.42, "num_turns": 7, "is_error": False}
    )
    result = run_claude(
        tmp_path,
        "ctx",
        execute=True,
        skip_permissions=False,
        max_turns=30,
        max_budget_usd=2.0,
        run=lambda argv, stdin_text, timeout, cwd: completed(stdout=payload),
    )
    assert result.ok
    assert result.cost_usd == pytest.approx(0.42)
    assert result.num_turns == 7


def test_run_claude_reports_error_payload_and_cost(tmp_path: Path) -> None:
    payload = json.dumps({"result": "hit max turns", "total_cost_usd": 1.9, "is_error": True})
    result = run_claude(
        tmp_path,
        "ctx",
        execute=True,
        skip_permissions=False,
        max_turns=30,
        max_budget_usd=2.0,
        run=lambda argv, stdin_text, timeout, cwd: completed(stdout=payload),
    )
    assert not result.ok
    assert result.cost_usd == pytest.approx(1.9)  # failed runs still cost money


def test_run_claude_handles_garbage_output(tmp_path: Path) -> None:
    result = run_claude(
        tmp_path,
        "ctx",
        execute=True,
        skip_permissions=False,
        max_turns=30,
        max_budget_usd=2.0,
        run=lambda argv, stdin_text, timeout, cwd: completed(stdout="not json"),
    )
    assert not result.ok


def test_wall_clock_timeout_kills_hung_process() -> None:
    """The real _run must kill a process that outlives the wall clock —
    this stub 'claude' sleeps for 60s but is killed within ~2s."""
    import sys
    import time

    from troupe.reeve.runner import _run

    hang = [sys.executable, "-c", "import time; time.sleep(60)"]
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run(hang, "work context", timeout_seconds=1.5, cwd=Path())
    assert time.monotonic() - start < 30  # killed promptly, not after 60s


def test_run_claude_converts_timeout_to_clean_failure(tmp_path: Path) -> None:
    def hanging_run(argv, stdin_text, timeout_seconds, cwd):
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout_seconds)

    result = run_claude(
        tmp_path,
        "ctx",
        execute=True,
        skip_permissions=False,
        max_turns=30,
        max_budget_usd=2.0,
        timeout_minutes=5,
        run=hanging_run,
    )
    assert not result.ok
    assert "wall-clock timeout" in result.error
    assert "5 minutes" in result.error


def test_cycle_threads_timeout_to_runner(project: Path) -> None:
    seen: dict = {}

    def fake_run_claude(root, ctx, **kwargs):
        seen.update(kwargs)
        return RunResult(ok=True, cost_usd=0.1, num_turns=1, text="")

    run_cycle(
        project,
        CycleOptions(execute=True, timeout_minutes=7.5),
        fetch=one_issue_fetch,
        run_claude=fake_run_claude,
    )
    assert seen["timeout_minutes"] == pytest.approx(7.5)


# ── cycle ────────────────────────────────────────────────────────────


def one_issue_fetch(label, limit, cwd):
    return [Issue(number=3, title="crash", labels=("P0",), body="b")]


def test_triage_only_cycle_never_invokes_claude(project: Path) -> None:
    calls: list[str] = []

    def fake_run_claude(*args, **kwargs):
        calls.append("ran")
        return RunResult(ok=True, cost_usd=0, num_turns=0, text="")

    report = run_cycle(
        project, CycleOptions(execute=False), fetch=one_issue_fetch, run_claude=fake_run_claude
    )
    assert calls == []
    assert any("triage-only" in line for line in report.lines)


def test_execute_cycle_runs_top_eligible_and_records_cost(project: Path) -> None:
    def fake_run_claude(root, ctx, **kwargs):
        assert "issue #3" in ctx
        assert kwargs["max_budget_usd"] == pytest.approx(2.0)
        return RunResult(ok=True, cost_usd=0.8, num_turns=5, text="done")

    report = run_cycle(
        project, CycleOptions(execute=True), fetch=one_issue_fetch, run_claude=fake_run_claude
    )
    assert report.executed_issue == 3
    assert report.cost_usd == pytest.approx(0.8)
    assert StateStore(project / ".troupe").daily_cost() == pytest.approx(0.8)


def test_daily_cap_stops_execution(project: Path) -> None:
    state = StateStore(project / ".troupe")
    state.record_cost(10.0)
    state.save()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("must not run claude past the daily cap")

    report = run_cycle(
        project, CycleOptions(execute=True), fetch=one_issue_fetch, run_claude=fail_if_called
    )
    assert any("daily cost cap reached" in line for line in report.lines)


def test_cycle_budget_shrinks_to_daily_remainder(project: Path) -> None:
    state = StateStore(project / ".troupe")
    state.record_cost(9.5)  # $0.50 left of the $10 day
    state.save()
    seen: dict = {}

    def fake_run_claude(root, ctx, **kwargs):
        seen.update(kwargs)
        return RunResult(ok=True, cost_usd=0.1, num_turns=1, text="")

    run_cycle(
        project, CycleOptions(execute=True), fetch=one_issue_fetch, run_claude=fake_run_claude
    )
    assert seen["max_budget_usd"] == pytest.approx(0.5)


def test_failed_run_triggers_backoff_skip_next_cycle(project: Path) -> None:
    def failing_run(*args, **kwargs):
        return RunResult(ok=False, cost_usd=0.2, num_turns=30, text="", error="max turns")

    report = run_cycle(
        project, CycleOptions(execute=True), fetch=one_issue_fetch, run_claude=failing_run
    )
    assert not report.ok

    def fail_if_called(*args, **kwargs):
        raise AssertionError("issue is cooling down; nothing should run")

    report2 = run_cycle(
        project, CycleOptions(execute=True), fetch=one_issue_fetch, run_claude=fail_if_called
    )
    assert any("no eligible issues" in line for line in report2.lines)


def test_poll_failure_is_reported_not_raised(project: Path) -> None:
    def broken_fetch(label, limit, cwd):
        raise PollError("gh not authenticated")

    report = run_cycle(project, CycleOptions(), fetch=broken_fetch)
    assert not report.ok
    assert any("poll failed" in line for line in report.lines)


# ── CLI safety rails ─────────────────────────────────────────────────


def test_skip_permissions_requires_execute(project: Path) -> None:
    result = runner_cli.invoke(app, ["watch", str(project), "--skip-permissions", "--once"])
    assert result.exit_code == 2
    assert "requires --execute" in result.output


def test_watch_requires_troupe_project(tmp_path: Path) -> None:
    result = runner_cli.invoke(app, ["watch", str(tmp_path), "--once"])
    assert result.exit_code == 1


def test_reeve_stop_is_protected_from_agents(project: Path) -> None:
    from conftest import run_hook, write_payload

    proc = run_hook(project, "troupe_file_guard.py", write_payload(project, ".troupe/reeve-stop"))
    assert proc.returncode == 2  # agents cannot stop the watcher
