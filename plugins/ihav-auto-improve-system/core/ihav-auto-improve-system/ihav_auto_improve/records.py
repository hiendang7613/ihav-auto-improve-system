"""Record files: hashes, append-only JSONL logs, the run manifest and project identity."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from . import Refused

REVIEW_STATUSES = ("pass", "fail", "unscorable", "not_applicable")
SKIP_DIRS = {".git", ".ihav_space", "__pycache__", ".venv", "node_modules"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_json(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path: Path, text: str) -> bool:
    """Create a file; False when it already exists (never overwrite)."""
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(text)
        return True
    except FileExistsError:
        return False


def write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(canonical(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list:
    if not Path(path).exists():
        return []
    records = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except ValueError as exc:
                raise Refused(f"{path}:{number} is not valid JSON ({exc}); records are never repaired automatically")
    return records


def create_run(runs_dir: Path, manifest: dict) -> Path:
    """Make a new run folder with a unique id; an existing folder is never reused."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        stamp = datetime.now(timezone.utc)  # milliseconds keep name order chronological between runs
        run_id = stamp.strftime("%Y%m%dT%H%M%S") + f"{stamp.microsecond // 1000:03d}Z-" + secrets.token_hex(2)
        run_dir = runs_dir / run_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        body = {"run_id": run_id, "created": now(), "status": "running", **manifest}
        write_new(run_dir / "run.json", json.dumps(body, indent=1, ensure_ascii=False) + "\n")
        return run_dir
    raise Refused(f"could not find a free run id in {runs_dir}")


def manifest(run_dir: Path) -> dict:
    path = Path(run_dir) / "run.json"
    if not path.is_file():
        raise Refused(f"no run manifest at {path}")
    return read_json(path)


def close_run(run_dir: Path, status: str, **fields) -> dict:
    """Write the closing fields once; a closed manifest is never written again."""
    body = manifest(run_dir)
    if body["status"] != "running":
        raise Refused(f"run {body['run_id']} is already {body['status']}; its manifest is not rewritten")
    body.update(status=status, closed=now(), **fields)
    write_text_atomic(Path(run_dir) / "run.json", json.dumps(body, indent=1, ensure_ascii=False) + "\n")
    return body


def append_invocation(run_dir: Path, record: dict) -> None:
    if manifest(run_dir)["status"] != "running":
        raise Refused("invocations of a closed run are never added to")
    append_jsonl(Path(run_dir) / "invocations.jsonl", record)


def add_evaluation(run_dir: Path, record: dict) -> None:
    append_jsonl(Path(run_dir) / "evaluations.jsonl", {"at": now(), **record})


def add_review(run_dir: Path, target: dict, item: str, status: str, by: str, note: str) -> dict:
    """Record one agent judgment after checking that its target and rubric item exist."""
    body = manifest(run_dir)
    if status not in REVIEW_STATUSES:
        raise Refused(f"status must be one of {', '.join(REVIEW_STATUSES)}")
    if not by.strip():
        raise Refused("--by must name who judged")
    if "attempt" in target:
        attempt = next((a for a in body["attempts"] if a["attempt"] == target["attempt"]), None)
        if attempt is None:
            raise Refused(f"run {body['run_id']} has no case attempt {target['attempt']}")
        items = rubric_items(body, attempt["kind"])
        if item not in items:
            raise Refused(f"item {item!r} is not in the rubric for {attempt['kind']} cases: {', '.join(items) or 'none'}")
    else:
        known = {(r["id"], (r.get("variant") or {}).get("name")) for r in read_jsonl(Path(run_dir) / "invocations.jsonl")}
        if (target["invocation"], target.get("variant")) not in known:
            raise Refused(f"run {body['run_id']} has no invocation {target['invocation']} variant {target.get('variant')}")
    record = {"kind": "review", "target": target, "item": item, "status": status, "by": by, "note": note,
              "identity": body["identity"]["sha256"]}
    add_evaluation(run_dir, record)
    return record


def rubric_items(body: dict, kind: str) -> list:
    rubric = body["adapter"]["describe"]["rubric"]
    return list(rubric.get(kind, rubric.get("*", [])))


def identity(project: Path, patterns: list, always: list) -> dict:
    """Hash the candidate: files matching the adapter's patterns plus fixed files (the adapter itself)."""
    project = Path(project).resolve()
    files = {}
    for pattern in patterns:
        for path in sorted(project.glob(pattern)):
            rel = path.relative_to(project)
            if path.is_file() and not SKIP_DIRS.intersection(rel.parts[:-1]):
                files[rel.as_posix()] = sha256_file(path)
    for path in always:
        path = Path(path).resolve()
        files[path.relative_to(project).as_posix()] = sha256_file(path)
    return {"sha256": sha256_json({"patterns": sorted(patterns), "files": files}), "files": files}
