"""The folder each project gets: ./.ihav_space/ihav-auto-improve-system/<pipeline>/ (plan section 5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import TOOL, Refused
from .records import write_new

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TEMPLATES = Path(__file__).resolve().parent / "templates"
EMPTY_PROFILES = {
    "tiers": {
        "cheap": {"routes": {}},
        "standin": {"routes": {}},
        "prod": {"routes": {}},
    },
}


class Pipeline:
    def __init__(self, project: Path, name: str):
        if not NAME.match(name):
            raise Refused(f"pipeline name {name!r} must be letters, digits, '.', '_' or '-'")
        self.project = Path(project).resolve()
        self.name = name
        self.dir = space(self.project) / name
        self.adapter = self.dir / "adapter.py"
        self.profiles = self.dir / "profiles.json"
        self.cases = self.dir / "cases"
        self.inputs = self.dir / "inputs"
        self.variants = self.dir / "variants"
        self.runs = self.dir / "runs"
        self.cycle = self.dir / "CYCLE.md"
        self.decisions = self.dir / "decisions.md"
        self.verdicts = self.dir / "verdicts.jsonl"


def space(project: Path) -> Path:
    return Path(project).resolve() / ".ihav_space" / TOOL


def select(project: Path, name: str = None) -> Pipeline:
    """The named pipeline, or the only one when no name is given."""
    if not Path(project).is_dir():
        raise Refused(f"--project {project} is not a folder")
    if name:
        pipeline = Pipeline(project, name)
        if not pipeline.adapter.is_file():
            raise Refused(f"no pipeline {name!r}: {pipeline.adapter} is missing; run init first")
        return pipeline
    root = space(project)
    found = sorted(p.name for p in root.iterdir() if (p / "adapter.py").is_file()) if root.is_dir() else []
    if len(found) != 1:
        raise Refused(f"choose a pipeline with --pipeline; found {', '.join(found) or 'none'} in {root}")
    return Pipeline(project, found[0])


def init(project: Path, name: str, template: str) -> list:
    """Create the pipeline tree; every existing file is kept as it is."""
    if template != "generic":
        raise Refused(f"template {template!r} is not available in this version; use --template generic "
                      "(the ai-hub-sdk template is milestone M4)")
    if not Path(project).is_dir():
        raise Refused(f"--project {project} is not a folder")
    pipeline = Pipeline(project, name)
    for folder in (pipeline.cases, pipeline.inputs, pipeline.variants, pipeline.runs):
        folder.mkdir(parents=True, exist_ok=True)
    files = [
        (space(project) / "README.md", (TEMPLATES / "space_README.md").read_text(encoding="utf-8")),
        (pipeline.adapter, (TEMPLATES / "adapter_generic.py").read_text(encoding="utf-8")),
        (pipeline.profiles, json.dumps({"pipeline": name, **EMPTY_PROFILES}, indent=1) + "\n"),
        (pipeline.decisions, (TEMPLATES / "decisions.md").read_text(encoding="utf-8").format(pipeline=name)),
    ]
    return [(path, "created" if write_new(path, text) else "kept") for path, text in files]
