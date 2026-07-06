"""Packaging consistency checks."""

import json
from pathlib import Path

from troupe import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest_version_matches_package() -> None:
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "troupe"
    assert manifest["version"] == __version__, (
        "bump .claude-plugin/plugin.json together with troupe.__version__"
    )


def test_plugin_skill_exists_with_description() -> None:
    skill = (REPO_ROOT / "skills" / "troupe" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    assert "description:" in skill
    assert "--skip-permissions" in skill  # safety guidance must survive edits
