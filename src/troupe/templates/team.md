# Troupe

> The persistent AI cast for this project. Names, charters, and shared memory live in `.troupe/`; compiled agent definitions live in `.claude/agents/`.
$project_section
## Cast

$cast_table

## How this works

- Each cast member has a **charter** (`.troupe/agents/{name}/charter.md`) defining role and ownership, and a **history** (`.troupe/agents/{name}/history.md`) of accumulated project knowledge.
- The whole team shares `.troupe/decisions.md` (the append-only decision log), `.troupe/directives.md` (standing rules), `.troupe/focus.md` (what's active right now), and `.troupe/wisdom.md` (distilled, reusable patterns).
- When spawning teammates or subagents for this project, use the cast: spawn them by their agent definition name (e.g. the `wright` agent type) and address them by their cast name.

Commit the `.troupe/` directory. The team — names, knowledge, decisions — travels with the repo.
