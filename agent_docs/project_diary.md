# Project Diary

## Decisions and Lessons

- Rebranded the forked `codex_workflow` package to `vision`, including ownership
  markers, `~/.codex/vision` paths, lifecycle command forms, and
  `vision-<version>.zip` release assets.
- Kept the orchestration architecture unchanged; added shared, orchestrator, and
  Luna-subagent instruction blocks rather than replacing route policy.
- Added `vision --config orch sol|luna` by patching the top-level `model` in
  `~/.codex/config.toml` and recording the choice in a workflow-owned `[vision]`
  section; removal deletes only that section, not the user's model.
- Added native OpenCode support behind a platform abstraction rather than
  scattered conditionals. Canonical worker instructions live in
  `vision/workers/<role>.md` and are rendered to Codex TOML or OpenCode Markdown
  (`platforms/codex.py`, `platforms/opencode.py`).
- Kept one workflow: installation, updates, removal, configuration, and token
  reporting are platform-aware (`--platform codex|opencode|both`) but no second
  route or orchestration model was created.
- OpenCode worker permissions translate Codex sandbox semantics: read-only roles
  deny `edit` and `bash`, every worker denies `task`, and generated agent files
  are never hand-edited; worker models are stored in Vision-owned configuration.
- Split the Codex-specific token reporter into `report_tokens_codex.py` plus a
  new `report_tokens_opencode.py` behind a shared `report_tokens.py` entry point,
  keeping the identical six-column report.
- Added native command surfaces from one canonical mapping
  (`runtime/commands.py`): Codex `$vision-light|medium|heavy|install|update|
  config|remove` skills and OpenCode `/light|medium|heavy|install|update|
  config|remove` slash commands. Route commands activate the existing shared
  route; lifecycle commands call the deterministic runtime. Deliberately did not
  use legacy `~/.codex/prompts` custom slash commands.
