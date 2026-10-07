# .ihav_space/ihav-auto-improve-system

Working folder of the ihav-auto-improve-system plugin. One folder per pipeline:

```
<pipeline>/
  adapter.py        the project's adapter (made by init from a template, then edited; init never overwrites it)
  profiles.json     tier -> route -> endpoint, verbatim model id, credential variable name, capabilities, fallback
  cases/            frozen case sets (JSON)
  inputs/           media the cases use
  variants/<step>/  prompt, schema or field-description variants for step replays (JSON)
  runs/<run_id>/    run.json, invocations.jsonl, evaluations.jsonl, one folder per case, score.md, REPORT.md
  verdicts.jsonl    every verify result, append-only
  CYCLE.md          rebuilt from the records
  decisions.md      the admin's decisions, verbatim, written by people
```

Records are the evidence: `run.json` is written at the start and closed once, `*.jsonl` files are only appended
to, and the Markdown files are rebuilt from them. Do not edit records by hand.
