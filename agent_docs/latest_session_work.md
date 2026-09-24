# Latest Session Work

## Detailed Current State

Vision now has one workflow with two native runtime backends. A platform
abstraction under `vision/runtime/platforms/` owns client-specific paths and
rendering; shared route, capsule, ownership, and orchestration logic is
untouched.

## Session Changes

- Added `platforms/base.py`, `platforms/codex.py`, `platforms/opencode.py`, and a
  registry with platform detection.
- Added `workers/*.md` canonical instruction bodies plus `runtime/workers.py` and
  `scripts/sync_workers.py`; regenerated `agents/*.toml` from them.
- Added `runtime/platform_lifecycle.py` for `codex`, `opencode`, and `both`
  bootstrap/update/remove/config, and persisted selected platforms in
  `install_state.json`.
- Added `--platform codex|opencode|both` and `--opencode-home` to the CLI, with
  an interactive prompt when several clients are detected and `--json` is absent.
- Added OpenCode worker-model configuration using `provider/model#variant` ids
  stored in Vision-owned `config.json`, regenerating the affected agent file.
- Neutralized shared content with the `{{VISION_HOME}}` placeholder and generic
  parent-child wording; split the token reporter into Codex and OpenCode
  backends behind a shared entry point.
- Added OpenCode install/update/remove/config tests and OpenCode token-report
  tests; updated README and architecture docs.
- Added one canonical native command mapping (`runtime/commands.py`) rendered to
  Codex `$vision-*` skills and OpenCode `commands/*.md` slash commands, with
  `install_commands`, `remove_commands`, and `validate_commands` on each platform
  adapter, ownership state, update refresh, and isolation tests.

## Verification

- `python -B -m unittest discover -s scripts -p "test_*.py"` - 91 tests pass.
- `python -B vision/runtime/workflow.py validate --package-root vision --json`.
- `python -B scripts/package_release.py` - builds `dist/vision-1.0.0.zip`.

## Pending Work and Blockers

- End-to-end OpenCode Heavy-route run and real OpenCode session export
  verification on an OpenCode installation.

## Next Entry Point

Run `vision --install --platform opencode`, confirm the six subagents and seven
slash commands load, then exercise `/heavy` and the OpenCode token report.
