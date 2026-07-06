"""Reeve runtime state: cycle counter, daily cost ledger, per-issue backoff.

Lives at .troupe/.runtime/reeve-state.json (the .runtime dir gitignores
itself). Backoff tiers per issue, driven by consecutive failures:

  0 failures      — eligible
  1-2 failures    — cooling down for (failures * 2) cycles after each failure
  3+ failures     — escalated: skipped until a human intervenes
                    (`troupe watch --reset-backoff` clears the ledger)

Success on an issue resets its failure count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ESCALATION_THRESHOLD = 3
COOLDOWN_CYCLES_PER_FAILURE = 2


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str


class StateStore:
    def __init__(self, troupe_dir: Path) -> None:
        self._runtime_dir = troupe_dir / ".runtime"
        self._path = self._runtime_dir / "reeve-state.json"
        self._data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("cycle", 0)
        data.setdefault("day", "")
        data.setdefault("dailyCostUsd", 0.0)
        data.setdefault("issues", {})
        return data

    def save(self) -> None:
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        gitignore = self._runtime_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")
        self._path.write_text(
            json.dumps(self._data, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    # ── cycles ───────────────────────────────────────────────────────

    def begin_cycle(self) -> int:
        self._data["cycle"] += 1
        return self._data["cycle"]

    @property
    def cycle(self) -> int:
        return self._data["cycle"]

    # ── cost ledger ──────────────────────────────────────────────────

    def _roll_day(self) -> None:
        today = date.today().isoformat()
        if self._data["day"] != today:
            self._data["day"] = today
            self._data["dailyCostUsd"] = 0.0

    def record_cost(self, usd: float) -> None:
        self._roll_day()
        self._data["dailyCostUsd"] = round(self._data["dailyCostUsd"] + max(usd, 0.0), 6)

    def daily_cost(self) -> float:
        self._roll_day()
        return self._data["dailyCostUsd"]

    # ── backoff ledger ───────────────────────────────────────────────

    def _issue(self, number: int) -> dict:
        return self._data["issues"].setdefault(str(number), {"failures": 0, "cooldownUntil": 0})

    def record_failure(self, number: int) -> None:
        record = self._issue(number)
        record["failures"] += 1
        record["cooldownUntil"] = self.cycle + record["failures"] * COOLDOWN_CYCLES_PER_FAILURE

    def record_success(self, number: int) -> None:
        self._data["issues"].pop(str(number), None)

    def eligibility(self, number: int) -> Eligibility:
        record = self._data["issues"].get(str(number))
        if record is None:
            return Eligibility(True, "no prior failures")
        failures = record.get("failures", 0)
        if failures >= ESCALATION_THRESHOLD:
            return Eligibility(
                False,
                f"escalated after {failures} failures - needs a human "
                "(clear with `troupe watch --reset-backoff`)",
            )
        cooldown_until = record.get("cooldownUntil", 0)
        if self.cycle < cooldown_until:
            return Eligibility(
                False, f"cooling down until cycle {cooldown_until} ({failures} failure(s))"
            )
        return Eligibility(True, f"retry after {failures} failure(s)")

    def escalated(self) -> list[int]:
        return sorted(
            int(number)
            for number, record in self._data["issues"].items()
            if record.get("failures", 0) >= ESCALATION_THRESHOLD
        )

    def reset_backoff(self) -> None:
        self._data["issues"] = {}
