# ihav-auto-improve-system

A Claude Code and Codex plugin that turns "improve this AI pipeline" into rounds with recorded evidence. The
agent picks cases, looks at the results, diagnoses and changes prompts, schemas or code; a small runner records
every model call, rebuilds the reports and decides `keep | reject | inconclusive` only from valid comparisons.

Plan (approved 2026-10-07 13:21, bản 2, SHA-256 `8b878d4b…`):
`ai-image_tools/ai-image-studio/labs/plans/auto_improve_plugin_plan.md`.
Status: milestones M2 and M3 (offline, fake adapter). The ai-hub-sdk adapter template and OpenRouter routes are
milestone M4 and not in this version.

## How it works

| Part | Owner | Job |
|---|---|---|
| Skill (`SKILL.md`, one for both hosts) | plugin | the review and improve procedures for the agent |
| Runner (`plugins/ihav-auto-improve-system/core/.../scripts/ihav_auto_improve.py`) | plugin | checks the profile, calls the adapter, writes records, compares, builds reports, gives the verdict |
| Adapter (`.ihav_space/ihav-auto-improve-system/<pipeline>/adapter.py`) | project | runs the pipeline end to end, replays one call, makes project checks |

The runner is Python 3.9+ standard library. It runs the adapter in a fresh process of the project's interpreter
(`--python`), so the adapter can use the project's dependencies.

Layout: the repo root holds the two marketplace manifests, the docs and `tests/`; `plugins/ihav-auto-improve-system/`
holds both host manifests, the Claude skill (`claude/skills/`) and the core with the Codex skill (`core/`).

## Commands

```bash
S=plugins/ihav-auto-improve-system/core/ihav-auto-improve-system/scripts/ihav_auto_improve.py
python3 $S init demo --template generic --project . --python .venv/bin/python   # never overwrites
python3 $S cases --project . --python .venv/bin/python --n 6 --seed 1 [--hard]
python3 $S round --project . --python .venv/bin/python --cases seed1-n6 --tier cheap [--steps plan --variants a,b]
python3 $S evaluate --project . --run <run_id> --case random-001 --item looks_right --status pass --by CLAUDE_01
python3 $S verify --project . --baseline <run_id> --candidate <run_id>
python3 $S report --project .
python3 $S status --project .
```

`round` runs the adapter's offline checks first and stops before any model call if one fails or changes a file.
`--tier prod` needs `--approval "<the admin's words>"`.

## Records

```
.ihav_space/ihav-auto-improve-system/<pipeline>/
  adapter.py  profiles.json  cases/  inputs/  variants/<step>/  verdicts.jsonl  CYCLE.md  decisions.md
  runs/<run_id>/run.json  invocations.jsonl  evaluations.jsonl  <case>/  replay/  score.md  REPORT.md
```

- `run.json`: unique run id, frozen profile and its hash, adapter description, evaluator version, cases with
  identity hashes, candidate identity; closed once with expected, attempted, completed, failed and missing.
- `invocations.jsonl` (append-only): one line per model call, id `case/turn/step/n`, route, model requested and
  returned, rendered request envelope and its hash, usage, generation id, cost `value, unit, status`
  (`reported | estimated | pending | unavailable`; unknown is never 0), retry or fallback label.
- `evaluations.jsonl` (append-only): offline checks, the core's checks, the adapter's checks
  (`pass | fail | unscorable | not_applicable`, mandatory or graded) and the agent's reviews with who and when.
- `score.md`, `REPORT.md` and `CYCLE.md` are rebuilt from these files; `decisions.md` is written by people.

## Verdict

`keep` only when every mandatory check and agent review passed, every artifact exists and decodes, the offline
checks passed without changing files, the candidate ran end to end on the paired cases, the graded checks are not
worse than the baseline, and the candidate's files are still the ones that ran. Runs with different cases or
media, evaluator version, mandatory contract, profile or repeats are not compared. `reject` does not restore files.

## Not in v1

LLM case generation, LLM or VLM judges, video and audio stand-ins, automatic model swapping, parallel runs and
daemons. The `ai-hub-sdk` template, OpenRouter catalog candidates in `profiles.json` and the Codex image stand-in
come with M4.

## Development

```bash
python3 -m pytest -q
```

The tests use `tests/fake_adapter.py`: no model, no network, no SDK.
