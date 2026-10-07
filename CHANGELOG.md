# Changelog

## 0.1.0 — 2026-10-08

Milestones M2 and M3 of the approved plan, offline only.

- Runner core, Python standard library: `init`, `cases`, `round`, `evaluate`, `verify`, `report`, `status`, with
  `--project` and `--python` given explicitly.
- Records: `run.json` with a unique run id, closed once with expected, attempted, completed, failed and missing
  counts; append-only `invocations.jsonl` with invocation ids `case/turn/step/n`, the rendered request envelope and
  its hash, and costs as `reported | estimated | pending | unavailable` (unknown is never 0); append-only
  `evaluations.jsonl` and `verdicts.jsonl`; `score.md`, `REPORT.md` and `CYCLE.md` rebuilt from them.
- Execution profile resolved per tier before running; unmapped routes, missing capabilities and fallbacks the
  profile does not allow are refused; `prod` only with recorded approval; calls on other routes or with a changed
  model id fail the case.
- Adapter contract (`describe`, `run_e2e`, `run_step`, `checks_e2e`, `checks_step`) run in a fresh process of the
  project's interpreter, with a timeout that stops the whole process group.
- Verdict `keep | reject | inconclusive` from valid paired comparisons only, bound to the candidate's identity.
- Claude Code and Codex manifests, marketplaces and one shared skill with the review and improve procedures; the
  plugin lives in `plugins/ihav-auto-improve-system/`, as in the other ihav plugins (admin, 2026-10-07 21:35).
- Offline tests with a fake adapter.
