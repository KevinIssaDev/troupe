"""Shared write helpers for CLI commands that mutate protected `.troupe/`
state directly — bypassing the file-guard hook by construction, since these
writes are plain `Path` I/O from the `troupe` CLI process, never a Claude
Code tool call (`troupe_file_guard.py`'s `PreToolUse` registration only ever
sees `Write`/`Edit`/`NotebookEdit` calls from a live session).

Used by `troupe cast`'s retire path (`scaffold.py`) and `troupe charter`'s
apply path (`charters/editor.py`) — deliberately *not* a shared confirm
gate, since `cast`'s explicit-input flags skip confirmation by design while
`charter` previews a diff and confirms (or stages a proposal off a TTY).
Also deliberately not shared with `troupe_decision_log.py` (the
`TaskCompleted` hook), which stays stdlib-only and independent of the
installed `troupe` package version.
"""

from __future__ import annotations

from pathlib import Path


def backup_and_write(path: Path, content: str) -> None:
    """Back up `path`'s current content to a single rotating `<name>.bak`
    (overwritten each time, not a growing pile), then overwrite `path` with
    `content`. If `path` doesn't exist yet, no backup is written."""
    if path.exists():
        backup_path = path.with_name(path.name + ".bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def append_decision_entry(
    troupe_dir: Path, *, date: str, title: str, by: str, what: str, why: str
) -> None:
    """Append one decision-log entry to `decisions.md`, matching the format
    documented at the top of that file exactly."""
    entry = f"\n### {date}: {title}\n**By:** {by}\n**What:** {what}\n**Why:** {why}\n"
    path = troupe_dir / "decisions.md"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)
