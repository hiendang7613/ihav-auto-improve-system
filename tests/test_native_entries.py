"""Native entry check per host, offline: the command each SKILL.md gives runs a full fake cycle in a project."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from conftest import CHEAP, FAKE, PLUGIN, load_fake
from ihav_auto_improve import __version__
from test_skills import CLAUDE, CLAUDE_COMMAND, CODEX, CODEX_COMMAND


def entry(host):
    """The script path a host resolves from its manifest and SKILL.md."""
    if host == "claude":
        skills = PLUGIN / json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())["skills"]
        assert CLAUDE_COMMAND in CLAUDE.read_text(encoding="utf-8")
        assert (skills / "ihav-auto-improve-system/SKILL.md").resolve() == CLAUDE.resolve()
        return CLAUDE_COMMAND.split('"')[1].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))  # the installed plugin dir
    skills = PLUGIN / json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())["skills"]
    assert CODEX_COMMAND in CODEX.read_text(encoding="utf-8")
    assert (skills / "ihav-auto-improve-system/SKILL.md").resolve() == CODEX.resolve()
    return CODEX_COMMAND.split()[1].replace("<skill-directory>", str(CODEX.parent))


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_the_host_entry_runs_a_full_cycle_in_the_project_folder(host, tmp_path):
    script = entry(host)

    def run(*args, python=False):
        argv = [sys.executable, script, *args, "--project", str(tmp_path)] + (["--python", sys.executable] if python else [])
        done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr
        return done.stdout

    assert subprocess.run([sys.executable, script, "--version"], capture_output=True, text=True).stdout.strip() == __version__
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "plan.txt").write_text("Plan the layout.")
    run("init", "demo", python=True)
    pipeline = tmp_path / ".ihav_space" / "ihav-auto-improve-system" / "demo"
    shutil.copy(FAKE, pipeline / "adapter.py")
    profiles = json.loads((pipeline / "profiles.json").read_text())
    profiles["tiers"]["cheap"]["routes"] = CHEAP
    (pipeline / "profiles.json").write_text(json.dumps(profiles))
    (pipeline / "inputs" / "one.png").write_bytes(load_fake().png_bytes())
    run("cases", "--n", "1", "--seed", "1", python=True)
    for _ in range(2):
        run("round", "--cases", "seed1-n1", "--tier", "cheap", python=True)
    base, run_id = sorted(p.name for p in (pipeline / "runs").iterdir())
    for rid in (base, run_id):
        run("evaluate", "--run", rid, "--case", "random-001", "--item", "looks_right", "--status", "pass", "--by", host)
    assert "verdict: keep (unchanged)" in run("verify", "--baseline", base, "--candidate", run_id)
    assert str(pipeline / "runs" / run_id / "REPORT.md") in run("status")
    assert (pipeline / "runs" / run_id / "REPORT.md").is_file() and (pipeline / "CYCLE.md").is_file()
