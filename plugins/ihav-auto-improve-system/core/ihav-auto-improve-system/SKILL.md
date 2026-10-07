---
name: ihav-auto-improve-system
description: Improve an AI pipeline (LLM, image or other model steps) in rounds with recorded evidence - frozen test cases, end-to-end rounds on a chosen model tier, replays of single model calls with prompt or schema variants, agent review of every case, and a keep, reject or inconclusive verdict. Use when someone asks to set up or run an auto-improve loop, test prompts or schemas across cases, review a round, or decide whether a pipeline change can be kept.
---

# ihav-auto-improve-system

Run the bundled command for every step. Replace `<skill-directory>` with the installed directory that contains this `SKILL.md`. Use `python3` on macOS/Linux and `py -3` on Windows:

```bash
python3 <skill-directory>/scripts/ihav_auto_improve.py <command> --project <project-root> [--pipeline <name>] ...
```

Give `--project` every time: the root of the user's project, never this skill's folder. Give `--python` for `init`, `cases` and `round`: the project's own interpreter (for example `.venv/bin/python`); it runs the project's adapter. The state lives in `<project-root>/.ihav_space/ihav-auto-improve-system/<pipeline>/`. Add `--pipeline` when the project has more than one.

## Authority

- A round calls the models of the tier it is given. Run a round with real or paid model calls only when the user allowed that case. Approval of a plan is not permission to spend.
- The `prod` tier runs only with `--approval "<the user's words>"`; the words are recorded verbatim.
- No commit, push or credential change. Never read `.env` files. `profiles.json` names credential variables and never holds a key.
- The runner writes only its own folder and never restores files. You edit the adapter, prompts, schemas and code.

## Set up

1. `init <pipeline> --template generic --project <root> --python <exe>`. `init` never overwrites a file.
2. Edit `adapter.py`. `describe()` lists every model step (route, fallback, needs, `replayable`, prompt/schema/field files), the mandatory checks, the review rubric by case kind, offline checks that never modify files, and the identity paths of the candidate.
3. Fill `profiles.json` for the tier you will use: every route of every step and fallback, with endpoint, model id verbatim, credential variable name, capabilities and allowed fallbacks. A route with no mapping refuses the round before anything runs; there is no fallback to another tier.
4. Put media in `inputs/`, then `cases --n <N> --seed <S> [--hard]`. A case set is frozen; `--hard` adds bounds, invalid inputs and cases that failed before.

## Round

`round --cases <set> --tier cheap|standin|prod [--steps <step,...>] [--variants <name,...>] [--repeats <K>]` runs the offline checks first (a failure stops the round before any model call), then every case end to end, then replays. It prints the run id and writes `runs/<run_id>/REPORT.md` and `score.md`.

## review procedure

1. Read `runs/<run_id>/REPORT.md` and `score.md`. Failures are listed per case; never summarise them away.
2. For each case attempt, open its input and its artifacts in `runs/<run_id>/<case>/` and look at them: open each image, read each text. Judge every rubric item of the case's kind.
3. Record each judgment: `evaluate --run <run_id> --case <attempt> --item <item> --status pass|fail|unscorable|not_applicable --by <your name> --note "<what you saw>"`. For a replay, use `--invocation <id> --variant <name>`.
4. Never write a judgment into a Markdown file: the reports are rebuilt from the records. An item without a judgment stays pending and blocks keep.

## improve procedure

1. Diagnose each failure: prompt, schema or field description, code, routing, or a limit of the model. Fix only what is yours; record a model limit as a limit.
2. Prefer a simplification that keeps behaviour: remove duplicate rules and move fixed constraints into code. A simplification with no regression is kept as unchanged, not as a quality improvement.
3. For a step with `replayable: true`, write variants as `variants/<step>/<name>.json` and run `round ... --steps <step> --variants <a,b>`. Each recorded call is sent again with each variant; compare their checks in `REPORT.md`. A step with `replayable: false` is never replayed: test it end to end.
4. Choose one candidate, apply it, and run `round` again on the same case set, tier and repeats. Review it with the review procedure.
5. `verify --baseline <run_id> --candidate <run_id>`. keep needs every mandatory check and review passed, decodable artifacts, passed offline checks, a valid paired comparison that is not worse, and an unchanged candidate. reject does not restore files: restore your own change and say so. inconclusive lists what is missing; do that and verify again.
6. After a keep, the candidate run is the next baseline. A change to an identity file after verify voids the evidence; `status` shows it.
7. Report to the user: cases, verdict and reasons, cost with unknown costs listed apart, the change, and the next step. `report` and `status` rebuild and show the state at any time.

## Valid comparison

Two runs are compared only with the same cases and media, evaluator version, mandatory contract, profile and repeats. New cases count only after both versions ran them. An unknown cost is never 0.
