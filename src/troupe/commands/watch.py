"""`troupe watch` — Reeve's polling loop.

Safety model:
  default            read-only triage report (no writes, no agent runs, no cost)
  --execute          dispatch governed headless Claude runs (acceptEdits +
                     a narrow gh allowlist)
  --skip-permissions pass --dangerously-skip-permissions to those runs;
                     refused unless --execute is also given

Stop a running watch cleanly by creating `.troupe/reeve-stop` in the project;
Reeve finishes the current cycle, removes the sentinel, and exits.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Annotated

import typer

from troupe.reeve.cycle import CycleOptions, run_cycle
from troupe.reeve.state import StateStore

SENTINEL = "reeve-stop"
_SLEEP_SLICE_SECONDS = 5

PathArg = Annotated[
    Path, typer.Argument(help="Project root to watch (defaults to the current directory).")
]


def watch(
    path: PathArg = Path(),
    interval: Annotated[
        float, typer.Option("--interval", min=1, help="Minutes between cycles.")
    ] = 10,
    once: Annotated[
        bool, typer.Option("--once", help="Run a single cycle and exit (cron-friendly).")
    ] = False,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Dispatch agent runs. Without this, watch is read-only."),
    ] = False,
    skip_permissions: Annotated[
        bool,
        typer.Option(
            "--skip-permissions",
            help="Run agents with --dangerously-skip-permissions. Requires --execute.",
        ),
    ] = False,
    label: Annotated[
        str, typer.Option("--label", help="Only watch issues carrying this label.")
    ] = "troupe",
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
    max_turns: Annotated[
        int, typer.Option("--max-turns", min=1, help="Agentic turn cap per run.")
    ] = 30,
    max_cost_per_cycle: Annotated[
        float, typer.Option("--max-cost-per-cycle", min=0.01, help="USD cap per cycle.")
    ] = 2.0,
    max_cost_per_day: Annotated[
        float, typer.Option("--max-cost-per-day", min=0.01, help="USD cap per day.")
    ] = 10.0,
    timeout_minutes: Annotated[
        float,
        typer.Option(
            "--timeout-minutes",
            min=1,
            help="Hard wall-clock kill for each agent run, on top of turn/budget caps.",
        ),
    ] = 30.0,
    reset_backoff: Annotated[
        bool,
        typer.Option("--reset-backoff", help="Clear the per-issue failure ledger, then continue."),
    ] = False,
) -> None:
    """Poll GitHub issues and triage them; with --execute, work them."""
    root = path.resolve()
    troupe_dir = root / ".troupe"
    if not troupe_dir.is_dir():
        typer.echo(f"error: no .troupe/ in {root} - run `troupe init` first", err=True)
        raise typer.Exit(code=1)
    if skip_permissions and not execute:
        typer.echo(
            "error: --skip-permissions requires --execute. Reeve never bypasses "
            "permissions in triage-only mode.",
            err=True,
        )
        raise typer.Exit(code=2)

    if reset_backoff:
        state = StateStore(troupe_dir)
        state.reset_backoff()
        state.save()
        typer.echo("backoff ledger cleared")

    options = CycleOptions(
        label=label,
        limit=limit,
        execute=execute,
        skip_permissions=skip_permissions,
        max_turns=max_turns,
        max_cost_per_cycle=max_cost_per_cycle,
        max_cost_per_day=max_cost_per_day,
        timeout_minutes=timeout_minutes,
    )

    mode = "EXECUTE" if execute else "triage-only"
    typer.echo(f"Reeve watching '{label}' issues in {root} [{mode}]")
    if not once:
        typer.echo(f"cycle every {interval:g} min; stop with: touch .troupe/{SENTINEL}")

    while True:
        report = run_cycle(root, options)
        typer.echo(f"--- cycle {report.cycle} ---")
        for line in report.lines:
            typer.echo(f"  {line}")
        if once:
            raise typer.Exit(code=0 if report.ok else 1)
        if _stopped(troupe_dir):
            typer.echo("reeve-stop sentinel found - exiting cleanly")
            return
        _sleep_until_next_cycle(troupe_dir, interval)
        if _stopped(troupe_dir):
            typer.echo("reeve-stop sentinel found - exiting cleanly")
            return


def _stopped(troupe_dir: Path) -> bool:
    sentinel = troupe_dir / SENTINEL
    if sentinel.exists():
        with contextlib.suppress(OSError):
            sentinel.unlink()
        return True
    return False


def _sleep_until_next_cycle(troupe_dir: Path, interval_minutes: float) -> None:
    deadline = time.monotonic() + interval_minutes * 60
    while time.monotonic() < deadline:
        if (troupe_dir / SENTINEL).exists():
            return
        time.sleep(min(_SLEEP_SLICE_SECONDS, max(deadline - time.monotonic(), 0.1)))
