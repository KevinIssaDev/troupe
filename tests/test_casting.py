import pytest

from troupe.casting.registry import CastExhaustedError, allocate, load_pool


def test_affinity_allocation_default_cast() -> None:
    cast = allocate(["lead", "backend", "frontend", "tester"], taken=set())
    names = {m.role: m.name for m in cast}
    assert names == {
        "lead": "Wright",
        "backend": "Mason",
        "frontend": "Webster",
        "tester": "Sawyer",
    }


def test_duplicate_roles_get_distinct_names() -> None:
    cast = allocate(["backend", "backend", "backend"], taken=set())
    names = [m.name for m in cast]
    assert len(set(names)) == 3
    assert names[0] == "Mason"


def test_taken_names_are_never_reallocated() -> None:
    cast = allocate(["lead"], taken={"wright"})
    assert cast[0].name != "Wright"
    assert cast[0].role == "lead"


def test_unknown_role_falls_back_to_first_unused() -> None:
    cast = allocate(["astrologer"], taken=set())
    assert cast[0].name  # got someone
    assert cast[0].role == "astrologer"


def test_exhaustion_raises() -> None:
    pool_size = len(load_pool())
    with pytest.raises(CastExhaustedError):
        allocate(["generalist"] * (pool_size + 1), taken=set())


def test_allocation_is_deterministic() -> None:
    roles = ["lead", "security", "devops", "docs"]
    first = [m.name for m in allocate(roles, taken=set())]
    second = [m.name for m in allocate(roles, taken=set())]
    assert first == second
