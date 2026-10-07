"""Both hosts install the same plugin name and version, and their skill paths exist."""

from __future__ import annotations

import json
import re

from conftest import PLUGIN, ROOT
from ihav_auto_improve import __version__


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_host_manifests_share_name_version_and_license():
    claude, codex = load(PLUGIN / ".claude-plugin/plugin.json"), load(PLUGIN / ".codex-plugin/plugin.json")
    assert claude["name"] == codex["name"] == "ihav-auto-improve-system"
    assert claude["version"] == codex["version"] == __version__
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = metadata.split("[project]", 1)[1].split("\n[", 1)[0]
    assert re.search(r'^\s*version\s*=\s*"([^"]+)"', project, re.MULTILINE).group(1) == __version__
    assert claude["license"] == codex["license"] == "MIT"
    assert claude["skills"] == "./claude/skills" and codex["skills"] == "./core/"
    assert "never falls back to production" in codex["interface"]["longDescription"]


def test_both_marketplaces_point_to_the_plugin_and_skill_paths_exist():
    claude_market = load(ROOT / ".claude-plugin/marketplace.json")
    codex_market = load(ROOT / ".agents/plugins/marketplace.json")
    assert claude_market["plugins"][0]["name"] == codex_market["plugins"][0]["name"] == "ihav-auto-improve-system"
    assert claude_market["plugins"][0]["source"] == codex_market["plugins"][0]["source"]["path"] == \
        "./plugins/ihav-auto-improve-system"
    assert (PLUGIN / "claude/skills/ihav-auto-improve-system/SKILL.md").is_file()
    assert (PLUGIN / "core/ihav-auto-improve-system/SKILL.md").is_file()
    assert (PLUGIN / "core/ihav-auto-improve-system/scripts/ihav_auto_improve.py").is_file()
    for stale in ("skills", "claude", "core", ".codex-plugin", ".claude-plugin/plugin.json"):
        assert not (ROOT / stale).exists(), stale
