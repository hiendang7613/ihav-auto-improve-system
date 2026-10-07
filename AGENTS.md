# ihav-auto-improve-system: agent rules

- Source of truth for scope: the approved plan `ai-image_tools/ai-image-studio/labs/plans/auto_improve_plugin_plan.md`
  (bản 2, SHA-256 `8b878d4b…`). A change outside it needs a new plan and the admin's approval.
- Layout: host manifests in `plugins/ihav-auto-improve-system/.claude-plugin/` and `.codex-plugin/`; the Claude skill in
  `claude/skills/`; the shared core, Codex skill and entry script in `core/ihav-auto-improve-system/`. The
  marketplace manifests at the repo root point to `./plugins/ihav-auto-improve-system`.
- The core in `plugins/ihav-auto-improve-system/core/ihav-auto-improve-system/` is Python 3.9+ standard library only. JSON for records and config;
  no YAML, no SDK, no network.
- The adapter runs in the project's interpreter (`--python`) through `scripts/adapter_host.py`; the host must not
  import the core package.
- Records are evidence: `run.json` is closed once, `*.jsonl` files are append-only, Markdown is rebuilt from them.
  Never write a judgment or a count straight into Markdown.
- Keep the two `SKILL.md` files in step (`tests/test_skills.py` checks it). Keep versions equal in both host
  manifests, `pyproject.toml` and `ihav_auto_improve/__init__.py`.
- Tests: `python3 -m pytest -q` from the repo root. They use `tests/fake_adapter.py`; no test may call a model or
  the network.
- No commit, push, new remote, credential change or paid call without the admin's explicit permission. Do not
  read `.env` files.
