"""One skill for both hosts: the same procedures, only the command path differs."""

from __future__ import annotations

import re

from conftest import PLUGIN

CLAUDE = PLUGIN / "claude/skills/ihav-auto-improve-system/SKILL.md"
CODEX = PLUGIN / "core/ihav-auto-improve-system/SKILL.md"
CLAUDE_COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT}/core/ihav-auto-improve-system/scripts/ihav_auto_improve.py"'
CODEX_COMMAND = "python3 <skill-directory>/scripts/ihav_auto_improve.py"


def body(path):
    return path.read_text(encoding="utf-8").split("\n---\n", 1)[1]


def test_both_skills_have_the_same_procedures():
    codex = body(CODEX).replace("Replace `<skill-directory>` with the installed directory that contains this "
                                "`SKILL.md`. ", "").replace(CODEX_COMMAND, CLAUDE_COMMAND)
    assert codex == body(CLAUDE)


def test_the_skill_holds_the_review_and_improve_procedures_and_the_rules():
    text = body(CODEX)
    for phrase in ("## review procedure", "## improve procedure", "evaluate --run", "verify --baseline",
                   "--approval", "never overwrites", "replayable: false", "Never read `.env`",
                   "reject does not restore files", "An unknown cost is never 0", "py -3",
                   "Never write a judgment into a Markdown file"):
        assert phrase in text, phrase
    for command in ("init", "cases", "round", "evaluate", "verify", "report", "status"):
        assert re.search(rf"`{command}\b", text), command


def test_frontmatter_names_match_and_claude_allows_only_the_bundled_command():
    for path in (CLAUDE, CODEX):
        assert path.read_text(encoding="utf-8").startswith("---\nname: ihav-auto-improve-system\ndescription: ")
    front = CLAUDE.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/core/ihav-auto-improve-system/scripts/" in front
