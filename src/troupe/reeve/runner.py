"""Headless `claude -p` invocation for Reeve's execute mode.

Deliberately NOT `--bare`: governance hooks, CLAUDE.md, and the compiled
cast definitions must be active during unattended work. The project's
settings are ALSO passed explicitly via `--settings` so governance keeps
firing when `--bare` becomes the default for `-p` (per current docs).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ClaudeRunner = Callable[[Sequence[str], str, float, Path], "subprocess.CompletedProcess[str]"]

# Hard wall-clock ceiling per headless run — the last line of defense when
# --max-turns and --max-budget-usd can't help (e.g. a permission prompt or
# network stall leaves the process wedged without consuming turns or budget).
DEFAULT_TIMEOUT_MINUTES = 30.0

# Execute mode runs at acceptEdits plus this narrow allowlist: enough to
# inspect the repo/issue and report back, nothing repo-destructive. Wider
# access requires the user's explicit --skip-permissions.
EXECUTE_ALLOWED_TOOLS = (
    "Bash(gh issue view *)",
    "Bash(gh issue comment *)",
    "Bash(gh issue list *)",
    "Bash(git status *)",
    "Bash(git diff *)",
    "Bash(git log *)",
)


@dataclass(frozen=True)
class RunResult:
    ok: bool
    cost_usd: float
    num_turns: int
    text: str
    error: str = ""


def build_argv(
    root: Path,
    *,
    execute: bool,
    skip_permissions: bool,
    max_turns: int,
    max_budget_usd: float,
    claude_cmd: str = "claude",
) -> list[str]:
    from troupe.reeve.context import DISPATCH_PROMPT

    argv = [
        claude_cmd,
        "-p",
        DISPATCH_PROMPT,
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        "--max-budget-usd",
        f"{max_budget_usd:.2f}",
        "--settings",
        str(root / ".claude" / "settings.json"),
    ]
    if skip_permissions:
        argv.append("--dangerously-skip-permissions")
    elif execute:
        argv += [
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            ",".join(EXECUTE_ALLOWED_TOOLS),
        ]
    return argv


def _run(
    argv: Sequence[str], stdin_text: str, timeout_seconds: float, cwd: Path
) -> subprocess.CompletedProcess[str]:
    # cwd must be the watched project: claude discovers .claude/, CLAUDE.md,
    # and the agent's gh calls resolve the repo from the working directory.
    return subprocess.run(  # noqa: S603 — list form, no shell
        list(argv),
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_seconds,
        cwd=str(cwd),
    )


def run_claude(
    root: Path,
    work_context: str,
    *,
    execute: bool,
    skip_permissions: bool,
    max_turns: int,
    max_budget_usd: float,
    timeout_minutes: float = DEFAULT_TIMEOUT_MINUTES,
    claude_cmd: str = "claude",
    run: ClaudeRunner = _run,
) -> RunResult:
    argv = build_argv(
        root,
        execute=execute,
        skip_permissions=skip_permissions,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        claude_cmd=claude_cmd,
    )
    try:
        proc = run(argv, work_context, timeout_minutes * 60, root)
    except subprocess.TimeoutExpired:
        return RunResult(
            ok=False,
            cost_usd=0.0,
            num_turns=0,
            text="",
            error=(
                f"wall-clock timeout: claude did not finish within "
                f"{timeout_minutes:g} minutes and was killed"
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RunResult(ok=False, cost_usd=0.0, num_turns=0, text="", error=f"claude: {exc}")

    payload: dict = {}
    try:
        parsed = json.loads(proc.stdout or "")
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        pass

    cost = float(payload.get("total_cost_usd") or 0.0)
    turns = int(payload.get("num_turns") or 0)
    text = str(payload.get("result") or "")

    if proc.returncode != 0:
        detail = text or (proc.stderr or "").strip() or f"exit {proc.returncode}"
        return RunResult(ok=False, cost_usd=cost, num_turns=turns, text=text, error=detail)
    if not payload:
        return RunResult(
            ok=False, cost_usd=0.0, num_turns=0, text="", error="claude returned no JSON"
        )
    if payload.get("is_error"):
        return RunResult(
            ok=False, cost_usd=cost, num_turns=turns, text=text, error=text or "is_error"
        )
    return RunResult(ok=True, cost_usd=cost, num_turns=turns, text=text)
