"""Shared helpers: a temporary project with the fake adapter, driven through the real command line."""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "ihav-auto-improve-system"
CORE = PLUGIN / "core" / "ihav-auto-improve-system"
SCRIPT = CORE / "scripts" / "ihav_auto_improve.py"
FAKE = Path(__file__).with_name("fake_adapter.py")
sys.path.insert(0, str(CORE))

from ihav_auto_improve.cli import main  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def load_fake():
    spec = importlib.util.spec_from_file_location("fake_adapter", FAKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def route(model, capabilities, fallback=()):
    return {"endpoint": "https://openrouter.ai/api/v1", "model": model, "credential_env": "OPENROUTER_API_KEY",
            "capabilities": list(capabilities), "fallback": list(fallback)}


CHEAP = {
    "llm_main": route("vendor/demo:free", ["structured_output"], ["llm_backup"]),
    "llm_backup": route("vendor/backup", ["structured_output"]),
    "image_main": route("vendor/image", ["image"]),
}


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.dir = root / ".ihav_space" / "ihav-auto-improve-system" / "demo"

    def cli(self, command, *args):
        argv = [command, "--project", str(self.root), *args]
        if command in ("init", "cases", "round"):
            argv += ["--python", sys.executable]
        return main(argv)

    def set_prompt(self, text):
        (self.root / "prompts" / "plan.txt").write_text(text, encoding="utf-8")

    def set_fake(self, **config):
        (self.root / "fake.json").write_text(json.dumps(config), encoding="utf-8")

    def set_routes(self, tier, routes):
        path = self.dir / "profiles.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body["tiers"][tier]["routes"] = routes
        path.write_text(json.dumps(body), encoding="utf-8")

    def add_variant(self, step, name, content):
        folder = self.dir / "variants" / step
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")

    def runs(self):
        return sorted(p.name for p in (self.dir / "runs").iterdir())

    def round(self, *args, cases="base", expect=0):
        assert self.cli("round", "--cases", cases, "--tier", "cheap", *args) == expect
        return self.runs()[-1]

    def manifest(self, run):
        return json.loads((self.dir / "runs" / run / "run.json").read_text(encoding="utf-8"))

    def records(self, run, name):
        path = self.dir / "runs" / run / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def review_all(self, run, status="pass", only=None):
        body = self.manifest(run)
        rubric = body["adapter"]["describe"]["rubric"]
        for attempt in body["attempts"]:
            for item in rubric.get(attempt["kind"], rubric.get("*", [])):
                chosen = status if only in (None, attempt["attempt"]) else "pass"
                assert self.cli("evaluate", "--run", run, "--case", attempt["attempt"], "--item", item,
                                "--status", chosen, "--by", "test-agent") == 0

    def verify(self, baseline, candidate):
        assert self.cli("verify", "--baseline", baseline, "--candidate", candidate) == 0
        lines = (self.dir / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])

    def baseline(self):
        run = self.round()
        self.review_all(run)
        return run


def make_project(root: Path) -> Project:
    project = Project(root)
    (root / "prompts").mkdir()
    project.set_prompt("Plan the layout.")
    project.set_fake()
    assert project.cli("init", "demo") == 0
    shutil.copy(FAKE, project.dir / "adapter.py")  # the project edits its adapter after init
    project.set_routes("cheap", CHEAP)
    (project.dir / "inputs" / "one.png").write_bytes(load_fake().png_bytes())
    assert project.cli("cases", "--n", "2", "--seed", "7", "--name", "base") == 0
    return project


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path)
