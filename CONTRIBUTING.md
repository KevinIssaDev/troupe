# Contributing to Troupe

Troupe is a `uv`-managed Python project. This doc covers the mechanics of
getting set up, running the checks CI runs, and submitting a change — not a
mission statement. For what the project *is*, see [README.md](README.md).

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/KevinIssaDev/troupe && cd troupe
uv sync --dev
```

This installs the package plus the dev dependency group (`pytest`, `ruff`,
`pyright`) from `pyproject.toml`.

## Running the checks

These are the same four steps CI runs (`.github/workflows/ci.yml`), in the
same order, on Ubuntu, macOS, and Windows against Python 3.11 and 3.13.
Run them all before opening a PR:

```bash
uv run ruff check .           # lint
uv run ruff format --check .  # formatting (use `uv run ruff format .` to fix)
uv run pyright                # type check
uv run pytest                 # test suite
```

Cross-platform correctness is a first-class concern here, not an
afterthought — use `pathlib` for paths and list-form `subprocess` args, never
`shell=True` string concatenation. `gh` and `claude` invocations are stubbed
throughout the test suite, so tests never hit the network or spend money.

If you're touching packaging (`pyproject.toml`, `MANIFEST.in`, template data
under `src/troupe/templates/`), also run:

```bash
uv build
uv run --no-project python scripts/check_wheel.py dist
```

This is the same check CI's `build` job runs to catch package data missing
from the built wheel.

## Repo workflow

This repository follows a few rules that apply to every contributor, human
or agent, and that this repo's own troupe cast (see below) is bound by too:

- **Feature branches only.** Never commit or push directly to `main`.
  Branch, commit, open a PR.
- **No tags, no releases from a branch.** Releases are a manual step the
  project owner takes; PRs should never create or push a git tag or trigger
  the release workflow.
- **One PR per substantive change.** Keep each PR's diff coherent and
  reviewable — don't bundle unrelated fixes into one branch.
- **Never skip hooks or bypass signing** (`--no-verify`, `--no-gpg-sign`)
  unless a maintainer explicitly asks for it.

Open a PR against `main` with a short description of what changed and why.
Reference the issue it closes, if any.

## The troupe cast in this repo

This repository scaffolds itself with its own product: a persistent, named
AI cast lives in `.troupe/` (charters, shared decision log, standing
directives) and compiled agent definitions live in `.claude/agents/`. If
you're working in this repo with Claude Code, you'll encounter that cast —
Wright (lead), Mason (backend), Sawyer (tester) — and its standing rules in
`.troupe/directives.md`.

A few things worth knowing as a contributor:

- `.troupe/decisions.md` is an append-only architectural decision log. Skim
  it for context before making a design call that might already have been
  made; add an entry (format documented at the top of the file) when you
  make one worth recording.
- `.claude/hooks/*.py` and `.claude/agents/*.md` are troupe-owned, generated
  files — they're refreshed by `troupe upgrade` from
  `src/troupe/templates/`. Don't hand-edit the copies in `.claude/`; change
  the template source instead, or the file-guard hook will block the write
  anyway.
- `.troupe/agents/*/charter.md` and `history.md`, `.troupe/team.md`, and
  `.troupe/directives.md` are hand-maintained team state, not templated —
  editing those directly is normal.

None of this changes how you contribute code; it's context so the hooks and
cast references you'll see in this repo don't feel unexplained.

## Reporting bugs / requesting features

Open a GitHub issue. If it's actionable by an autonomous agent run, label it
`troupe` — Reeve (`troupe watch`) can pick it up, though execution is
opt-in and never runs against this repo without a maintainer enabling it.
