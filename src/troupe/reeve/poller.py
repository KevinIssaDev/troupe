"""GitHub issue polling via the `gh` CLI (read-only)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

GhRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class PollError(Exception):
    """Raised when the gh CLI fails or returns unusable output."""


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    labels: tuple[str, ...] = ()
    url: str = ""
    body: str = ""
    priority: int = field(default=9, compare=False)


def _run_gh(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — list form, no shell
        list(argv), capture_output=True, text=True, timeout=60, encoding="utf-8"
    )


def fetch_issues(label: str, limit: int, run: GhRunner = _run_gh) -> list[Issue]:
    argv = [
        "gh",
        "issue",
        "list",
        "--state",
        "open",
        "--label",
        label,
        "--limit",
        str(limit),
        "--json",
        "number,title,labels,url,body",
    ]
    try:
        proc = run(argv)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PollError(f"could not run gh: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise PollError(f"gh issue list failed (exit {proc.returncode}): {stderr}")
    try:
        raw = json.loads(proc.stdout or "[]")
    except ValueError as exc:
        raise PollError(f"gh returned invalid JSON: {exc}") from exc

    issues = []
    for item in raw:
        labels = tuple(entry["name"] for entry in item.get("labels", []) if isinstance(entry, dict))
        issues.append(
            Issue(
                number=int(item["number"]),
                title=str(item.get("title", "")),
                labels=labels,
                url=str(item.get("url", "")),
                body=str(item.get("body") or ""),
                priority=_priority(labels),
            )
        )
    return issues


def _priority(labels: tuple[str, ...]) -> int:
    """Lower is more urgent. Unlabeled issues sit between P2 and P3."""
    lowered = {label.lower() for label in labels}
    table = (
        (0, {"p0", "priority:critical", "critical", "urgent"}),
        (1, {"p1", "priority:high", "high"}),
        (2, {"p2", "priority:medium", "medium"}),
        (4, {"p3", "priority:low", "low"}),
    )
    for rank, names in table:
        if lowered & names:
            return rank
    return 3


def prioritize(issues: list[Issue]) -> list[Issue]:
    """Most urgent first; ties broken by age (lower issue number first)."""
    return sorted(issues, key=lambda issue: (issue.priority, issue.number))
