# Design: cast recast/retire tooling (`troupe cast`)

**Status:** Draft — awaiting Kevin's review and sign-off. Not yet implemented;
this document only.
**Author:** Wright (Lead)
**Date:** 2026-07-07

## Problem

Once `troupe init` casts a team, there is no supported way to change the
roster. Growing it (a project picks up auth code and now wants a security
specialist) or shrinking it (a headless CLI project was mis-cast with a
Webster, or a role genuinely stops being needed) both require hand-editing
`casting-state.json` and `.claude/agents/*.md` directly — exactly the kind
of manual state surgery troupe exists to avoid, and exactly the files
`.troupe/policy.json` marks as protected because agents should never
freehand them.

Two related-but-separate gaps, both closed by this design:

1. No CLI surface exists to add a role or retire a member after `init`.
2. No live-session mechanism exists for a cast member playing lead to *act*
   on a request like "add a security specialist" other than reaching for a
   text editor on governance files it isn't supposed to touch.

Directive from Kevin: ship `troupe cast --add-role <role>` and
`troupe cast --retire <name>` as a new, deterministic CLI command, reusing
`allocate()`/`scaffold()` machinery where it fits; retiring must archive,
never destroy, a member's `charter.md`/`history.md`; and both a live-lead
conversational path and an explicit slash command must exist to invoke it.

## Mechanism: one command, two flags

```
troupe cast [PATH] [--add-role ROLE ...] [--retire NAME ...] [--reason TEXT]
```

- `--add-role` is a repeatable option (Typer `list[str]`, one value per
  occurrence — `troupe cast --add-role security --add-role data` casts two
  new members in one call). Matches `--roles`' comma-free repeatable-flag
  shape rather than reusing `--roles`' CSV convention, because `--add-role`
  names one role per flag by design (the flag is singular).
- `--retire` is likewise repeatable, matched against a cast member's slug
  (== `name.lower()`, so `--retire webster` and `--retire Webster` are
  identical — case-insensitive lookup against `casting-state.json`'s
  `assignments` keys, which *are* slugs).
- `--reason` is optional free text folded into the decision-log entry (see
  below). Omitting it is allowed — the log still gets written, honestly
  stating no reason was given, rather than fabricating one.
- Neither flag given: `"Nothing to add or retire - pass --add-role or --retire."`,
  exit 2 — same shape as `init.py`'s existing "No roles requested" empty-CSV
  check.
- No TTY confirmation prompt, no `--dry-run`. Unlike scan-aware init's
  *auto-proposed* roster (which needs a confirm gate because the roles
  weren't the user's literal words), every role and name here is named
  explicitly by the caller — this mirrors `troupe init --roles ...`'s
  existing behavior: **explicit input bypasses the prompt.** "Deterministic
  CLI command" in Kevin's spec is read as "no interactive gate," matching
  that precedent rather than inventing a new one.
- Both flags can appear in the same invocation (retire one, add another in
  one shot — "swap Webster for a security specialist"). Retires are applied
  before adds, deterministically, so one `troupe cast` call reads as one
  atomic roster change and produces exactly one decision-log entry.

CLI wiring follows the established split (Wright's own learning from the
`/troupe-explore` review): a thin Typer wrapper at
`src/troupe/commands/cast.py` (parse flags, call the core functions, format
stdout, set exit codes), registered in `src/troupe/cli.py` next to the other
three (`app.command()(cast)`). All actual logic lives in `src/troupe/scaffold.py`
(the existing home of `load_state`/`_save_state`/`members_from_state`/`allocate`
orchestration), not the wrapper.

## Reuse vs. new logic

### `--add-role`: reuses `scaffold()` unmodified (after one bugfix — see below)

This is the headline reuse win. `scaffold()` already computes a **multiset
diff** between requested role ids and the roles of currently-active members
(`_missing_requests`), allocates only the gap via `allocate()`, writes each
new member's charter/history/agent-definition files, updates `casting-state.json`,
and regenerates `team.md`'s cast table — all of it already idempotent and
already exercised by every `troupe init --roles ...` call today. Calling

```python
scaffold(root, roles=["security"])
```

on an already-cast repo does *exactly* what `--add-role security` needs: it
reads existing state, finds `security` isn't present, allocates one new
name for it, and writes only the new member's files, touching nothing else.
No new casting logic is needed for this path — `commands/cast.py`'s
`--add-role` handling is a direct pass-through to `scaffold(path, roles=add_roles)`.

One real gotcha to document, not fix: `_missing_requests` is a **multiset**
diff. `--add-role backend` when a backend member already exists is a no-op
(the existing member already "satisfies" one requested backend) — this
matches `troupe init --roles backend,backend` on a repo that already has one
backend today, so it isn't a new inconsistency, but it does mean "add a
*second* backend" requires `--add-role backend --add-role backend` (two
occurrences), not one. Worth a line in `--add-role`'s `--help` text.

### `--retire`: new logic, but small

Nothing today removes a member from the active roster — `scaffold()` only
ever adds. New function in `scaffold.py`:

```python
@dataclass
class RetireResult:
    root: Path
    retired: list[CastMember] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    already_retired: list[str] = field(default_factory=list)

def retire_members(root: Path, names: list[str]) -> RetireResult:
    """Archive one or more active cast members: status -> "retired" in
    casting-state.json, compiled .claude/agents/{slug}.md deleted so nothing
    can spawn them. charter.md and history.md are never touched."""
    root = root.resolve()
    troupe_dir = root / ".troupe"
    state = load_state(troupe_dir)
    result = RetireResult(root=root)
    now = datetime.now(UTC).isoformat(timespec="seconds")

    for raw_name in names:
        slug = raw_name.strip().lower()
        record = state["assignments"].get(slug)
        if record is None:
            result.not_found.append(raw_name)
            continue
        if record.get("status") != "active":
            result.already_retired.append(raw_name)
            continue
        record["status"] = "retired"
        record["retiredAt"] = now
        agent_def = root / ".claude" / "agents" / f"{slug}.md"
        agent_def.unlink(missing_ok=True)
        result.retired.append(CastMember(
            entry=PoolEntry(name=record["name"], craft=record.get("craft", ""), affinities=()),
            role=record["role"],
            charter=_charter_from_record(record),
        ))

    if result.retired:
        _save_state(troupe_dir, state)
        _rewrite_cast_table(troupe_dir / "team.md", members_from_state(state))

    return result
```

`_rewrite_cast_table` is a small extraction from the existing
`_sync_team_md`'s "regenerate the table between the `## Cast` marker and the
next `## ` heading" branch — that logic already renders the **complete
current roster** (`result.cast`, not just newly-added members) every time it
fires, so factoring it into a standalone helper both `_sync_team_md` (called
when `scaffold()` casts someone new) and `retire_members` (called
unconditionally, since team.md must reflect a retirement even though nobody
new was cast) can call is a refactor of existing behavior, not new
rendering logic:

```python
def _rewrite_cast_table(path: Path, active_members: list[CastMember]) -> None:
    if not path.exists():
        return
    table = _cast_table(active_members)
    text = path.read_text(encoding="utf-8")
    start = text.find("## Cast")
    if start == -1:
        return
    body_start = start + len("## Cast")
    next_section = text.find("\n## ", body_start)
    tail = text[next_section:] if next_section != -1 else ""
    path.write_text(text[:body_start] + "\n\n" + table + "\n" + tail, encoding="utf-8", newline="\n")
```

Because `members_from_state` already filters to `status == "active"`, a
retired member drops out of the rendered table automatically — no separate
"retired" row is printed in team.md; the archive lives entirely in
`casting-state.json`.

### A latent bug this feature would otherwise activate: name reuse after retirement

`registry.py`'s `allocate(roles, taken)` docstring is explicit: `taken`
"holds slugs of names already assigned in this project (**never
reallocated, even for retired members**)." But every current caller builds
`taken` from `members_from_state(state)` — which filters to **active**
members only:

```python
existing = members_from_state(state)   # scaffold.py:79, active-only
...
taken = {m.slug for m in existing}     # scaffold.py:83 — excludes retired slugs
```

Today this is dormant: nothing ever sets `status != "active"`, so
`existing` always equals "everyone ever cast" and the bug never surfaces.
The moment `retire_members` ships, it stops being dormant — retire Webster,
then run `troupe init --roles frontend` (or `--add-role frontend`) later,
and `allocate()` would be free to hand the name "Webster" to a brand-new
member, silently violating the "never reused, even for retired members"
invariant the code already documents as a requirement.

**Fix required as part of this feature** (small, in scope, not a design
change): both call sites (`scaffold()` and `preview_cast()`) must build
`taken` from **every slug ever recorded**, not just active ones:

```python
# before (scaffold.py, both call sites)
taken = {m.slug for m in existing}

# after
taken = set(state["assignments"].keys())
```

This is the one piece of "existing machinery" this design touches rather
than purely reuses — flagged explicitly because it's a correctness
prerequisite for retire to be safe, not a new feature.

### Decision-log entry: new, small, CLI-owned

`.troupe/decisions.md` is **not** in `policy.json`'s `protectedPaths` — it's
meant to be appended to routinely, and every design/decision so far has been
logged by whichever cast member or human made the call, by hand. `troupe cast`
is the first command that changes team composition *without* a live Claude
Code session necessarily being involved (a human could run it directly from
a terminal), so this design has the CLI append its own entry, deterministically,
after a successful run — otherwise roster changes made outside a session
would go unlogged.

```python
def _log_recast_decision(troupe_dir: Path, retired: list[CastMember], added: list[CastMember], reason: str | None) -> None:
    if not retired and not added:
        return
    what_parts = []
    if retired:
        what_parts.append("Retired " + ", ".join(f"{m.name} ({m.role})" for m in retired) + ".")
    if added:
        what_parts.append("Cast " + ", ".join(f"{m.name} ({m.effective_role().title})" for m in added) + ".")
    why = reason.strip() if reason and reason.strip() else "No reason given (--reason not passed)."
    entry = (
        f"\n### {date.today().isoformat()}: Cast change via `troupe cast`\n"
        f"**By:** troupe cast (CLI)\n"
        f"**What:** {' '.join(what_parts)}\n"
        f"**Why:** {why}\n"
    )
    path = troupe_dir / "decisions.md"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)
```

**By:** is fixed to `"troupe cast (CLI)"`, not a human name — the standing
directive (`directives.md`: never commit personal data) plus this project's
own explicit divergence from squad (no git `user.name` reads, ever,
documented in `docs/design/scan-aware-init.md` §4) both apply here
unchanged. If a human wants their own name attributed, `--reason` is free
text and they can put it there themselves; the CLI does not go looking for
who ran it.

## Retire semantics: archive, never destroy

Exactly per Kevin's spec, restated concretely against the actual schema
(`casting-state.json`, `STATE_VERSION = 1`, additive-only per the
scan-aware-init precedent that kept the version at 1 for the optional
`charter` block):

```json
"webster": {
  "name": "Webster", "role": "frontend", "craft": "...",
  "status": "retired",
  "assignedAt": "2026-07-06T09:52:08+00:00",
  "retiredAt": "2026-07-07T14:03:11+00:00"
}
```

- `status: "retired"` (new value; the only other value in use today is
  `"active"`) plus a new optional `retiredAt` timestamp field. Both additive
  — `STATE_VERSION` stays 1, same reasoning as the existing `charter` block:
  old readers that don't know about `"retired"` simply see a status string
  that isn't `"active"` and (via `members_from_state`'s existing
  `if record.get("status") != "active": continue` filter) already treat it
  as inactive correctly, with zero code changes needed in any reader that
  predates this feature.
- `.claude/agents/{slug}.md` is deleted (`Path.unlink(missing_ok=True)`) —
  the compiled agent definition is what actually lets Claude Code spawn a
  named subagent type; removing it is what makes "nothing can spawn them
  anymore" true. This file is derived/troupe-owned (refreshed by `upgrade`,
  never hand-edited), so deleting it destroys nothing a user authored.
- `.troupe/agents/{slug}/charter.md` and `.troupe/agents/{slug}/history.md`
  are **never touched, never even opened** by `retire_members`. This is a
  hard invariant, not a default: the function has no code path that writes
  to either file. Accumulated history stays on disk exactly as `/troupe-explore`
  and normal work left it — un-retiring a member later (out of scope for
  this design, but worth a passing thought) would find their memory intact.

## Two invocation surfaces

### 1. The live lead's own charter — conversational trigger

Kevin's ask: a user tells whichever cast member is playing lead in a live
Claude Code session "add a security specialist," and that lead runs
`troupe cast --add-role security` via Bash — not hand-editing
`casting-state.json` or writing charter files itself. Two concrete template
edits carry this:

**`src/troupe/casting/roles.py`** — the `lead` entry in `ROLE_CATALOG` gains
a fourth ownership bullet and an extended `use_hint`:

```python
# before
Role(
    id="lead",
    title="Lead",
    expertise="Architecture, technical decisions, code review, scope control",
    ownership=(
        "Architectural direction and cross-cutting design decisions",
        "Code review and quality gates",
        "Keeping scope honest — saying no is part of the job",
    ),
    use_hint="design decisions, reviews, and anything that spans more than one area",
),

# after
Role(
    id="lead",
    title="Lead",
    expertise="Architecture, technical decisions, code review, scope control",
    ownership=(
        "Architectural direction and cross-cutting design decisions",
        "Code review and quality gates",
        "Keeping scope honest — saying no is part of the job",
        "Growing or retiring the cast — run `troupe cast --add-role <role>` "
        "or `troupe cast --retire <name>` via Bash, never by hand-editing "
        "casting-state.json or writing/deleting charter or agent files directly",
    ),
    use_hint=(
        "design decisions, reviews, anything that spans more than one area, "
        "and growing or retiring the cast"
    ),
),
```

This flows automatically into every future-cast lead's `charter.md`
(`$ownership_bullets`) and compiled `agent.md` (`$ownership_bullets` and the
frontmatter `description: ... Use for $use_hint.` line) with **no template
file edits** — `charter.md`/`agent.md` already render whatever the catalog
(or a persisted specialization) says. Per the existing
`_write_if_missing` invariant, this only affects **newly cast** leads going
forward; this repo's own `.troupe/agents/wright/charter.md` (and any other
already-scaffolded repo's lead) is not rewritten — same as every prior
catalog-text change (backend's "Core" specialization, etc.). A user who
wants an existing lead's charter to mention this can add the bullet by
hand; it's their file.

**`src/troupe/templates/directives.md`** — one new standing-rule bullet,
readable by the whole cast (directives are universal law), naming this as
the lead's job specifically — same pattern as the existing "hand the rest
back to the lead" bullet:

```markdown
# before
- Read `.troupe/decisions.md` before starting work; record team-relevant choices there.
- Never commit secrets, credentials, or personal data to the repository.
- Work stays inside your charter's ownership area; hand the rest back to the lead.

# after
- Read `.troupe/decisions.md` before starting work; record team-relevant choices there.
- Never commit secrets, credentials, or personal data to the repository.
- Work stays inside your charter's ownership area; hand the rest back to the lead.
- Adding or retiring a cast member is the lead's call: run `troupe cast --add-role <role>`
  or `troupe cast --retire <name>` (via Bash) — never hand-edit `casting-state.json`
  or `.claude/agents/*.md` directly.
```

`directives.md` is in the "never touched after scaffold" bucket
(`upgrade.py`'s own module docstring lists it there), so — same caveat as
above — this reaches only newly-scaffolded repos, not this repo's own
`.troupe/directives.md`, unless a human edits it in by hand. That's
consistent with every other directives.md change this project has ever
made; there's no mechanism today for `upgrade` to patch user-owned text
files, and inventing one is out of scope here.

### 2. `.claude/commands/troupe-cast.md` — explicit slash-command shortcut

Same scaffold/upgrade force-refresh pattern established for
`/troupe-explore`: source of truth at
`src/troupe/templates/commands/troupe-cast.md`, written once by
`scaffold.py`'s `_write_if_missing` (alongside the existing
`troupe-explore.md` call), kept current by `upgrade.py`'s `_refresh`
(alongside the existing `troupe-explore.md` call) — it's a mechanism file,
not something a user hand-tunes per repo.

```markdown
---
description: Add a role to the cast or retire a cast member, via the troupe CLI.
allowed-tools: Bash
---

# /troupe-cast

Grow or retire the cast by running the `troupe cast` CLI — never by
editing `.troupe/casting-state.json` or `.claude/agents/*.md` directly.

## Steps

1. Work out from the request what's being asked:
   - Adding a role (e.g. "add a security specialist," "we need someone on
     docs") maps to `--add-role <role-id>`. Use a role id from the
     project's catalog if one clearly fits (lead, backend, frontend,
     tester, security, devops, docs, data, design); if the user names
     something that doesn't map to a known id, pass their word through
     as-is — `resolve_role()` synthesizes a generic charter for it, same
     as `--roles` does today.
   - Retiring someone (e.g. "retire Webster," "we don't need a frontend
     person anymore") maps to `--retire <name>`, using the cast member's
     name as it appears in `.troupe/team.md`'s `## Cast` table.
   - Both can apply to one request ("swap Webster for a security
     specialist" is `--retire webster --add-role security`).
2. Run `troupe cast [--add-role ROLE]... [--retire NAME]... [--reason "..."]`
   via Bash from the project root. Pass `--reason` with a short summary of
   why, taken from the user's own words, so the decision log the CLI
   writes is meaningful rather than empty.
3. Report back what changed: any new cast member's name and role, any
   retired member's name, and confirm their `history.md` was left intact
   (retiring never deletes it).
4. If the command errors (unknown role, name not found, already retired),
   relay the CLI's error message plainly — do not try to work around it by
   editing state files yourself.

## Notes

- This command's whole job is running the CLI correctly. It never edits
  `.troupe/casting-state.json`, `.claude/agents/*.md`, or any charter or
  history file itself.
- `troupe cast` requires the `troupe` package to be installed and on PATH
  in this environment; if the Bash call fails with "command not found,"
  say so rather than guessing at an alternative.
```

Net new files/edits (not implemented in this pass — design only):

- New: `src/troupe/templates/commands/troupe-cast.md` (content above).
- `src/troupe/scaffold.py`: one more `_write_if_missing(...)` call for the
  new path, alongside the existing `troupe-explore.md` line; plus the
  `retire_members`/`_rewrite_cast_table`/`_all_assigned_slugs`-fix additions
  described above.
- `src/troupe/upgrade.py`: one more `_refresh(...)` call, alongside the
  existing `troupe-explore.md` line; **and** its own module docstring's
  "Troupe-owned (refreshed to current templates)" list needs
  `.claude/commands/troupe-cast.md` added — Wright's own recorded learning
  from the `/troupe-explore` review is that this docstring list drifts
  silently if a new refreshed file forgets to update it.
- New: `src/troupe/commands/cast.py` (thin Typer wrapper), registered in
  `src/troupe/cli.py` (`app.command()(cast)`).
- `src/troupe/casting/roles.py`: the `lead` ownership/`use_hint` edit above.
- `src/troupe/templates/directives.md`: the one new bullet above.

## Security considerations: does the file guard catch a Bash-issued write?

Kevin asked for a definitive answer, not a guess, on whether
`troupe_file_guard.py`'s `PreToolUse` registration would also catch a
Bash-issued write or delete against a protected path (e.g.
`rm .claude/agents/wright.md`, or a Python one-liner writing
`casting-state.json` directly) — since this feature's own retire path does
exactly that kind of direct file I/O, and needs to understand whether it's
"exempt" from something or simply outside its scope.

**Finding, read directly from the shipped files, not inferred:**

`.claude/settings.json` (this repo's own, and the template it comes from)
registers the guard as:

```json
{
  "matcher": "Write|Edit|NotebookEdit",
  "hooks": [{"type": "command", "command": "python",
             "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/troupe_file_guard.py"]}]
}
```

Claude Code's `PreToolUse` `matcher` is a regex tested against the
**invoked tool's name**. `Bash` is a distinct tool name from `Write`,
`Edit`, and `NotebookEdit` — there is no `Bash`-matched or matcher-less
(`"*"`) `PreToolUse` registration anywhere in `.claude/settings.json` for
this hook (or any hook). **A Bash-issued file write or delete never invokes
this hook at all**, regardless of `protectedPaths`. This is definitive from
reading the registration, not a guess about hook semantics.

It is doubly true even hypothetically: `troupe_file_guard.py`'s
`target_path()` only reads `tool_input.file_path` / `tool_input.notebook_path`
(`WRITE_PATH_KEYS`) — the shape of `Write`/`Edit`/`NotebookEdit`'s own
parameters. `Bash`'s `tool_input` is `{"command": "...", ...}` with neither
key present. So even if someone broadened the matcher to include `Bash`,
the guard as written would find no target path in a Bash call and silently
return 0 (allow) for every single one — a second, independent gap on top of
the matcher scoping.

**Is this an exemption `troupe init`/`upgrade` rely on, or just unguarded?**
The latter — and this matters for how to think about it. `scaffold()`'s
`_write_if_missing`/`_save_state` and `upgrade()`'s `_refresh` all call
plain `Path.write_text()` / `Path.read_text()`. None of that ever goes
through a Claude Code tool call (`Write`, `Edit`, `NotebookEdit`, or
`Bash`) in the first place — the `troupe` CLI is a separate OS process
(a human's terminal, or an agent shelling out via `Bash` to invoke it),
not a Claude-Code-mediated file operation. Nothing "exempts" it from the
guard; it was never inside the guard's domain to begin with, because the
guard only ever sees Claude-Code-tool-mediated writes from a live session.
This design's `retire_members`/`--add-role` writes are the same shape as
every write `scaffold()`/`upgrade()` already do — precedent, not a new
category.

**Recommendation: accept this as a documented limitation, do not attempt to
close it as part of this feature.**

- Closing it properly would mean either widening the matcher to `Bash` (or
  `"*"`) and teaching `troupe_file_guard.py` to parse arbitrary shell
  command strings for file targets — `rm`, `mv`, `cp -T` onto a protected
  path, `sed -i`, output redirection (`>`, `>>`), a Python one-liner, a
  called script that itself writes the file — an open-ended command-parsing
  problem with no reliable general solution (quoting, indirection, `curl |
  sh`), and a much larger security-engineering effort than this feature's
  scope.
- The realistic threat model `protectedPaths` addresses is an agent, mid
  ordinary task, editing governance state it shouldn't via the tool it
  normally uses for file changes (`Write`/`Edit`) — including
  prompt-injection-driven edits (the same class of risk scan-aware-init's
  sanitization work defends against). An agent that already has
  unrestricted `Bash` access has a far larger blast radius available to it
  than editing one JSON file (arbitrary code execution, credential
  exfiltration, git history rewrites); treating this one hook as a
  boundary against a fully adversarial or compromised agent is the wrong
  threat model for it. The actual controls for that class of risk are
  session-level (Bash permission prompts, `allowed-tools` scoping, human
  review of diffs), not this hook.
- This feature's own legitimate writes need the same unguarded direct-I/O
  path regardless of whether the Bash-bypass gap for *live agents* were
  ever closed — the two are separable, but share the same underlying
  mechanism, so closing one wouldn't remove the need for the other to keep
  working.

This is stated the same way this project already discloses accepted gaps
(scan-aware-init.md's "Residual risk, accepted and stated" paragraph on
prompt injection; monorepo-scan.md's asserted-as-a-passing-test "accepted
limitation" on nested components) — a named, tested-as-such gap, not a
silent one. No test is proposed *for* this gap (there is nothing to assert
about an interception that provably cannot happen), but `--add-role`'s and
`--retire`'s own direct-I/O behavior should be tested for correctness
exactly as `scaffold()`/`upgrade()` already are.

One adjacent, smaller observation surfaced while checking this: `.claude/agents/*.md`
itself is **not** in `policy.json`'s `protectedPaths` today, even though
`upgrade.py`'s docstring calls it "troupe-owned, refreshed" and `.troupe/agents/*/charter.md`
(a much less operationally sensitive file, arguably) *is* protected. This
means a live agent could already freely `Write`/`Edit` its own compiled
`.claude/agents/{slug}.md` today, guard or no Bash gap, which is unrelated
to this feature's own (unguarded-by-construction) CLI-side deletion of that
file but is a real, pre-existing gap in the protected-paths list. Flagged
here as a finding, not fixed as part of this design — it's a one-line
`policy.json` addition (`".claude/agents/*.md"`) that's a separate,
reviewable change with its own blast radius to think through (e.g. would it
break anything `troupe upgrade` itself relies on writing through a
non-CLI path — it doesn't appear to, since `upgrade()` also writes directly,
not through a tool call, but that deserves its own look rather than
riding in on this PR).

## Relationship to a future `doctor` drift check

Not designed in full here — flagged the same way scan-aware-init.md pointed
at troupe-explore.md before that command existed.

`troupe doctor`'s `_check_cast` already iterates `members_from_state`
(active-only) and fails if an **active** member is missing any of their
three files, including `.claude/agents/{slug}.md`. Because retirement
removes the member from `members_from_state`'s output entirely, a properly
retired member causes zero doctor complaints — the existing check already
tolerates this feature correctly, no change needed there.

What doctor has no check for today, and could gain later: the **inverse**
drift — a `.claude/agents/{slug}.md` file on disk whose slug is *not* an
active member in `casting-state.json` (either retired, or removed from
state entirely by a hand-edit that bypassed `troupe cast`). That would be
an orphaned compiled definition: a spawnable agent type nobody on the
active roster maps to. A future `troupe doctor` check could glob
`.claude/agents/*.md`, diff the slugs found against active members, and
warn on any leftover — catching exactly the case where `casting-state.json`
was hand-edited to `"retired"` without going through this feature's own
delete-the-agent-def step. Not designing this now; noting the connection so
it isn't lost.

## Scope

Single PR once signed off:

- `src/troupe/scaffold.py`: `retire_members`, `RetireResult`,
  `_rewrite_cast_table` (extracted from `_sync_team_md`), the `taken`-set
  bugfix in both `scaffold()` and `preview_cast()`, `_log_recast_decision`,
  one `_write_if_missing` call for `troupe-cast.md`.
- `src/troupe/commands/cast.py` (new): thin Typer wrapper.
- `src/troupe/cli.py`: register `cast`.
- `src/troupe/casting/roles.py`: lead ownership/use_hint edit.
- `src/troupe/templates/directives.md`: one new bullet.
- `src/troupe/templates/commands/troupe-cast.md` (new): content above.
- `src/troupe/upgrade.py`: one `_refresh` call plus the module-docstring
  list update.
- Tests: name-reuse-after-retire regression (the bug this design's fix
  closes — retire a member, cast a new one for the freed role, assert the
  new member never receives the retired slug/name); `retire_members`
  correctness (status/`retiredAt` set, agent def deleted, charter/history
  untouched, team.md table drops the row); unknown-name and
  already-retired error paths; `--add-role` multiset gotcha (adding an
  already-present single role is a no-op, matching `--roles`' existing
  behavior); decision-log entry format and the no-`--reason` fallback text;
  scaffold/upgrade coverage for the new `troupe-cast.md` file (mirrors the
  existing `troupe-explore.md` assertions).

## Open questions for Kevin's sign-off

1. **Retiring the last active `lead` or `tester`.** No hard block is
   proposed — `retire_members` has no role-count policy layer today, and
   inventing one is a bigger change than this feature. Recommendation:
   allow it, print a plain warning ("no active lead remains" /
   "no active tester remains") to stdout, and let `troupe doctor` be where
   a human notices later if it matters. Open to Kevin overriding this with
   a hard block behind `--force`.
2. **`.claude/agents/*.md` missing from `protectedPaths`.** Flagged as a
   finding above; recommend a separate, small follow-up PR rather than
   folding it into this one.
3. **Un-retiring.** Out of scope for this design entirely — `charter.md`/
   `history.md` surviving intact means a manual `status: "active"` edit
   plus re-running `troupe upgrade` (to regenerate the compiled agent def
   from the still-present state record) would resurrect a retired member
   today, informally. Worth a deliberate `--reinstate` flag later if this
   comes up in practice; not designing it now.

---

## Proposed decision entries (copy into `.troupe/decisions.md` after sign-off)

### 2026-07-07: `troupe cast --add-role`/`--retire` — reuse scaffold(), archive not destroy
**By:** Wright (design), Kevin (review pending final sign-off)
**What:** New `troupe cast` CLI command. `--add-role` is a direct pass-through to the existing `scaffold(root, roles=[...])` (zero new casting logic — the multiset gap-fill it already does is exactly "add one more role"). `--retire` is new: marks `casting-state.json`'s assignment `status: "retired"` with a `retiredAt` timestamp (additive, `STATE_VERSION` stays 1) and deletes the compiled `.claude/agents/{slug}.md`; `.troupe/agents/{slug}/charter.md` and `history.md` are never touched by the retire path. A latent name-reuse bug (`allocate()`'s `taken` set was built from active-only members, contradicting its own "never reallocated, even for retired members" docstring) is fixed as a prerequisite: `taken` now derives from every slug ever recorded in state, not just active ones.
**Why:** `allocate()`/`scaffold()` already do everything `--add-role` needs; duplicating that logic would be pure risk for no benefit. Retirement must be reversible-in-spirit (history/charter preserved) per Kevin's explicit spec, and the name-reuse bug had to be fixed here because retirement is the first thing that could ever trigger it.

### 2026-07-07: Recast/retire decision logging is CLI-owned, attributed to the tool not a person
**By:** Wright (design), Kevin (review pending final sign-off)
**What:** `troupe cast` appends its own `.troupe/decisions.md` entry after a successful run (`**By:** troupe cast (CLI)`), summarizing what was added/retired, with an optional `--reason` folded into the `**Why:**` line (defaulting to an honest "no reason given" rather than a fabricated one).
**Why:** Roster changes can now happen outside a live Claude Code session (a human running the CLI directly); without this, those changes would go unlogged. Attribution is fixed to the tool, not a git-config name, per this project's standing divergence from squad: no personal data, ever, read or seeded into the repo.

### 2026-07-07: Bash-issued writes bypass the file guard entirely — accepted, not closed
**By:** Wright (design), Kevin (review pending final sign-off)
**What:** Confirmed by reading `.claude/settings.json` and `troupe_file_guard.py` directly: the guard's `PreToolUse` registration matches only the `Write`/`Edit`/`NotebookEdit` tool names, and its own path-extraction logic only reads keys those three tools populate. A Bash-issued write or delete against any `protectedPaths` entry is never intercepted, full stop — not a corner case, a structural scoping fact. This feature's own `retire_members` writes the same way `scaffold()`/`upgrade()` already do (plain `Path` I/O from the `troupe` CLI process, outside any Claude Code tool call), which is precedent, not a new exemption.
**Why:** Closing the gap would require parsing arbitrary shell command strings for file targets — an open-ended problem out of proportion to this feature, and the wrong threat model besides (an agent with Bash access already has a far larger blast radius than one guarded JSON file). Documented as an accepted, tested-as-such limitation, matching this project's existing disclosure pattern for the prompt-injection residual risk in scan-aware-init.md and the nested-component tradeoff in monorepo-scan.md.
