"""End-to-end tests for `troupe init`: run against a temp dir, assert the tree.

Scaffold-outcome tests use `--no-scan` so the roster is DEFAULT_ROLES exactly as
before scan-aware init (byte-identical path). The confirm-gate matrix below
covers the scan-aware flow itself: non-TTY refusal, prompt yes/no/EOF,
`--dry-run`, `--roles` bypass, and idempotent re-runs.
"""

import json
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import troupe.commands.init as init_command
from troupe.cli import app
from troupe.discovery.advisor import propose_plan
from troupe.discovery.scanner import scan
from troupe.scaffold import preview_cast, scaffold

runner = CliRunner()


def run_init(path: Path, *args: str) -> str:
    result = runner.invoke(app, ["init", str(path), *args])
    assert result.exit_code == 0, result.output
    return result.output


def fake_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make init believe stdin is a TTY so the confirm prompt is reached; the
    prompt itself still reads from CliRunner's injected input."""
    monkeypatch.setattr(
        init_command,
        "sys",
        types.SimpleNamespace(stdin=types.SimpleNamespace(isatty=lambda: True)),
    )


def wrote_nothing(root: Path) -> bool:
    return not (root / ".troupe").exists() and not (root / ".claude").exists()


def write_python_cli(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "sqctl"',
                'description = "A tiny CLI."',
                'dependencies = ["typer>=0.12"]',
                "",
                "[project.scripts]",
                'sqctl = "sqctl.cli:main"',
                "",
                "[tool.pytest.ini_options]",
                'testpaths = ["tests"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_cli.py").write_text("def test_ok() -> None: ...\n", encoding="utf-8")


# ── scaffold outcome (pre-scan behavior via --no-scan) ───────────────


def test_init_creates_expected_tree(tmp_path: Path) -> None:
    run_init(tmp_path, "--no-scan")

    for rel in (
        ".troupe/team.md",
        ".troupe/decisions.md",
        ".troupe/directives.md",
        ".troupe/config.json",
        ".troupe/casting-state.json",
        ".troupe/agents/wright/charter.md",
        ".troupe/agents/wright/history.md",
        ".troupe/agents/mason/charter.md",
        ".troupe/agents/webster/charter.md",
        ".troupe/agents/sawyer/charter.md",
        ".claude/agents/wright.md",
        ".claude/agents/mason.md",
        ".claude/agents/webster.md",
        ".claude/agents/sawyer.md",
        ".claude/commands/troupe-explore.md",
    ):
        assert (tmp_path / rel).is_file(), f"missing {rel}"


def test_init_next_steps_points_to_explore(tmp_path: Path) -> None:
    output = run_init(tmp_path, "--no-scan")
    assert "Next: commit .troupe/ and .claude/ so the team travels with the repo." in output
    assert "Then: open Claude Code and run /troupe-explore, or tell the team directly." in output


def test_agent_definition_has_valid_frontmatter(tmp_path: Path) -> None:
    run_init(tmp_path, "--no-scan")
    text = (tmp_path / ".claude/agents/wright.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: wright" in text
    assert "description: Wright" in text
    assert "You are **Wright**" in text


def test_team_md_lists_full_cast(tmp_path: Path) -> None:
    run_init(tmp_path, "--no-scan")
    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    for name in ("Wright", "Mason", "Webster", "Sawyer"):
        assert name in team


def test_reinit_preserves_state(tmp_path: Path) -> None:
    run_init(tmp_path, "--no-scan")

    decisions = tmp_path / ".troupe/decisions.md"
    history = tmp_path / ".troupe/agents/wright/history.md"
    decisions.write_text("# Decisions\n\n### 2026-07-06: Chose sqlite\n", encoding="utf-8")
    history.write_text("# Wright — History\n\nLearned things.\n", encoding="utf-8")

    run_init(tmp_path, "--no-scan")

    assert "Chose sqlite" in decisions.read_text(encoding="utf-8")
    assert "Learned things." in history.read_text(encoding="utf-8")


def test_reinit_with_new_role_extends_cast(tmp_path: Path) -> None:
    run_init(tmp_path, "--no-scan")
    run_init(tmp_path, "--roles", "lead,backend,frontend,tester,security")

    assert (tmp_path / ".troupe/agents/ward/charter.md").is_file()
    assert (tmp_path / ".claude/agents/ward.md").is_file()

    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert set(state["assignments"]) == {"wright", "mason", "webster", "sawyer", "ward"}

    # team.md roster table was regenerated to include Ward, around user content
    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    assert "Ward" in team


def test_reinit_same_roles_casts_nothing_new(tmp_path: Path) -> None:
    run_init(tmp_path, "--no-scan")
    before = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    output = run_init(tmp_path, "--no-scan")
    after = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert before == after
    assert "Already on the roster" in output


def test_no_scan_output_has_no_project_context(tmp_path: Path) -> None:
    # --no-scan is the pre-scan escape hatch: no project sections, no leftover
    # placeholders — the rendered files match the pre-scan templates.
    run_init(tmp_path, "--no-scan")
    charter = (tmp_path / ".troupe/agents/wright/charter.md").read_text(encoding="utf-8")
    assert "$project_context" not in charter
    assert "## Project context" not in charter
    expertise_then_ownership = (
        "- **Expertise:** Architecture, technical decisions, code review, scope control"
        "\n\n## Ownership"
    )
    assert expertise_then_ownership in charter
    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    assert "## Project" not in team
    assert not (tmp_path / ".troupe/profile.json").exists()


# ── confirm gate: no file before confirmation ────────────────────────


def test_bare_init_non_tty_refuses_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 2
    assert "non-interactive: pass --yes" in result.output
    assert wrote_nothing(tmp_path)


def test_prompt_declined_exits_0_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    result = runner.invoke(app, ["init", str(tmp_path)], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Cast this team?" in result.output
    assert "Nothing written" in result.output
    assert wrote_nothing(tmp_path)


def test_prompt_accepted_scaffolds_proposed_cast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tty(monkeypatch)
    result = runner.invoke(app, ["init", str(tmp_path)], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Cast this team?" in result.output
    # An empty repo proposes lead + tester only — no backend, no frontend.
    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    assert set(state["assignments"]) == {"wright", "sawyer"}


def test_prompt_eof_refuses_like_non_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # stdin claims to be a TTY but the prompt hits EOF (Mason's decision entry:
    # typer.Abort is treated exactly like the non-TTY case).
    fake_tty(monkeypatch)
    result = runner.invoke(app, ["init", str(tmp_path)], input="")
    assert result.exit_code == 2
    assert "non-interactive: pass --yes" in result.output
    assert wrote_nothing(tmp_path)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing written." in result.output
    assert wrote_nothing(tmp_path)


def test_dry_run_with_roles_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--dry-run", "--roles", "lead,backend"])
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing written." in result.output
    assert wrote_nothing(tmp_path)


def test_dry_run_with_yes_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--dry-run", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing written." in result.output
    assert wrote_nothing(tmp_path)


def test_roles_bypasses_prompt_in_non_tty(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--roles", "lead,tester"])
    assert result.exit_code == 0, result.output
    assert "Cast this team?" not in result.output
    assert (tmp_path / ".troupe/casting-state.json").is_file()


def test_dry_run_on_covered_roster_prints_dry_run_line(tmp_path: Path) -> None:
    # Every --dry-run path ends with the same closing line, including the
    # nothing-new-to-cast case.
    write_python_cli(tmp_path)
    run_init(tmp_path, "--yes")

    before = (tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8")
    result = runner.invoke(app, ["init", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Roster already covers the detected stack" in result.output
    assert "Dry run: nothing written." in result.output
    assert (tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8") == before


def test_reinit_covered_roster_skips_prompt(tmp_path: Path) -> None:
    write_python_cli(tmp_path)
    run_init(tmp_path, "--yes")

    # Bare re-run, non-TTY: the roster covers the stack, so no prompt, no
    # refusal, and nothing new is written.
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Roster already covers the detected stack" in result.output
    assert "Cast this team?" not in result.output
    assert "non-interactive" not in result.output
    assert "Created 0 file(s)" in result.output


def test_no_scan_dry_run_writes_nothing(tmp_path: Path) -> None:
    # Distinct code path from every other --dry-run test: with --no-scan,
    # `plan` is None, so init() takes the `elif dry_run:` branch and prints
    # via `_echo_roles_preview` rather than `_echo_proposal` — previously
    # untested (every other --dry-run test scans by default).
    result = runner.invoke(app, ["init", str(tmp_path), "--no-scan", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Would cast:" in result.output
    assert "Dry run: nothing written." in result.output
    assert wrote_nothing(tmp_path)


def test_no_scan_dry_run_with_roles_writes_nothing(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["init", str(tmp_path), "--no-scan", "--dry-run", "--roles", "lead,tester"]
    )
    assert result.exit_code == 0, result.output
    assert "Would cast:" in result.output
    assert "Dry run: nothing written." in result.output
    assert wrote_nothing(tmp_path)


# ── scan-aware casting ───────────────────────────────────────────────


def test_preview_cast_names_match_scaffold(tmp_path: Path) -> None:
    write_python_cli(tmp_path)
    plan = propose_plan(scan(tmp_path))
    ids = [proposal.role.id for proposal in plan.proposals]

    existing, previewed = preview_cast(tmp_path, ids)
    assert existing == []

    result = scaffold(tmp_path, plan=plan)
    assert [m.name for m in previewed] == [m.name for m in result.cast_added]


def test_scan_aware_init_persists_specialized_charter(tmp_path: Path) -> None:
    write_python_cli(tmp_path)
    output = run_init(tmp_path, "--yes")
    assert "Core" in output  # backend shows its specialized title in the echo

    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    mason = state["assignments"]["mason"]
    assert mason["role"] == "backend"  # id stays stable; title is presentation
    assert mason["charter"]["title"] == "Core"
    # lead is never specialized, so no charter block is persisted for it
    assert "charter" not in state["assignments"]["wright"]

    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    assert "| Mason | Core |" in team
    assert "## Project" in team
    assert (tmp_path / ".troupe/profile.json").is_file()

    charter = (tmp_path / ".troupe/agents/mason/charter.md").read_text(encoding="utf-8")
    assert "## Project context" in charter
    assert '- Project: "sqctl"' in charter


def write_howler_shape(root: Path) -> None:
    """No root manifest; ui/ (React), client/ (Python + tests), api/ (Python)
    — mirrors tests/test_discovery.py's fixture of the same name."""
    (root / "ui").mkdir()
    (root / "ui" / "package.json").write_text(
        json.dumps({"name": "ui", "dependencies": {"react": "^18.2.0"}}), encoding="utf-8"
    )
    (root / "client").mkdir()
    (root / "client" / "pyproject.toml").write_text(
        '[project]\nname = "client"\n', encoding="utf-8"
    )
    (root / "api").mkdir()
    (root / "api" / "pyproject.toml").write_text(
        '[project]\nname = "api"\ndependencies = ["fastapi"]\n', encoding="utf-8"
    )


def test_monorepo_proposal_shows_components_and_skips_core_title(tmp_path: Path) -> None:
    write_howler_shape(tmp_path)
    output = run_init(tmp_path, "--yes")

    assert "Core" not in output  # monorepo backend keeps the plain "Backend" title

    team = (tmp_path / ".troupe/team.md").read_text(encoding="utf-8")
    assert "Components:" in team
    assert '"api/"' in team and '"client/"' in team and '"ui/"' in team
    assert "| Mason | Backend |" in team

    state = json.loads((tmp_path / ".troupe/casting-state.json").read_text(encoding="utf-8"))
    mason = state["assignments"]["mason"]
    assert mason["role"] == "backend"
    assert "charter" not in mason or mason["charter"].get("title") != "Core"

    profile = json.loads((tmp_path / ".troupe/profile.json").read_text(encoding="utf-8"))
    assert profile["kind"] == "monorepo"
    assert profile["components"] == ["api", "client", "ui"]
    assert profile["components_truncated"] == 0
