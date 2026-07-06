"""Name-pool allocation: deterministic, affinity-first, never reuses a name."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files

from troupe.casting.roles import Role, resolve_role


class CastExhaustedError(Exception):
    """Raised when the name pool has no unused names left."""


@dataclass(frozen=True)
class PoolEntry:
    name: str
    craft: str
    affinities: tuple[str, ...]

    @property
    def slug(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class CastMember:
    entry: PoolEntry
    role: str
    #: Specialized charter persisted at cast time (scan-aware init); None means
    #: "resolve from the static catalog" — the behavior for all pre-scan casts.
    charter: Role | None = None

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def slug(self) -> str:
        return self.entry.slug

    def effective_role(self) -> Role:
        """The persisted specialized charter if one exists, else the catalog role."""
        return self.charter if self.charter is not None else resolve_role(self.role)


def load_pool() -> list[PoolEntry]:
    raw = json.loads(files("troupe.casting").joinpath("names.json").read_text(encoding="utf-8"))
    return [
        PoolEntry(name=e["name"], craft=e["craft"], affinities=tuple(e["affinities"]))
        for e in raw["names"]
    ]


def allocate(roles: list[str], taken: set[str]) -> list[CastMember]:
    """Assign one pool name per requested role.

    Allocation is deterministic: for each role (in request order), the first
    unused pool entry whose affinities include the role wins; if none match,
    the first unused entry of any affinity is used. `taken` holds slugs of
    names already assigned in this project (never reallocated, even for
    retired members).
    """
    pool = load_pool()
    used = {t.lower() for t in taken}
    cast: list[CastMember] = []
    for role in roles:
        pick = next((e for e in pool if role in e.affinities and e.slug not in used), None)
        if pick is None:
            pick = next((e for e in pool if e.slug not in used), None)
        if pick is None:
            raise CastExhaustedError(
                f"Name pool exhausted: {len(pool)} names, all assigned. "
                f"Cannot cast a member for role '{role}'."
            )
        used.add(pick.slug)
        cast.append(CastMember(entry=pick, role=role))
    return cast
