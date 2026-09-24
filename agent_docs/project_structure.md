# Project Structure

## Directory Layout

- `vision/` - the packaged workflow source and release payload root.
  - `vision/runtime/` - deterministic lifecycle Python runtime.
  - `vision/runtime/platforms/` - Codex and OpenCode runtime backends
    (`base.py`, `codex.py`, `opencode.py`).
  - `vision/workers/` - canonical, platform-neutral worker instruction bodies
    (`<role>.md`).
  - `vision/operate/` - bootstrap, install, update, check-update, config, and
    remove guides plus `VERSION` and `user_AGENTS.md`.
  - `vision/agents/` - rendered Codex worker TOML definitions.
  - `vision/skills/` - workflow-owned skills (`deployment-token-report`), with a
    shared token-report entry point and per-platform backends.
  - `vision/project_docs/` - project documentation templates.
  - `vision/medium_route.md`, `vision/heavy_route.md`, `vision/archivist.md` -
    route and closure policy (platform-resolved workflow home).
- `scripts/` - release packaging, worker sync, and regression test suites.
- `docs/` - runtime architecture and historical release notes.
- `benchmarks/`, `light_benchmark/` - workflow benchmarks.
- `.github/workflows/release.yml` - tag-driven release build and publish.
- `agent_docs/` - this project's durable documentation (installed).

## Modules and Responsibilities

- `runtime/workflow.py` - CLI entry point, platform selection, and argument
  parsing.
- `runtime/lifecycle.py` - Codex bootstrap/update/remove/config plan
  composition.
- `runtime/platform_lifecycle.py` - platform-aware composition for `codex`,
  `opencode`, and `both`.
- `runtime/platforms/base.py` - shared platform contract.
- `runtime/platforms/codex.py` - Codex backend (existing behavior).
- `runtime/platforms/opencode.py` - OpenCode backend (native Markdown subagents
  and ownership).
- `runtime/workers.py` - canonical worker store loader and Codex renderer.
- `runtime/commands.py` - canonical native command mapping and renderers for
  Codex skills and OpenCode slash commands.
- `runtime/session_usage.py` - platform-neutral token-report dispatch.
- `runtime/project_ops.py` - project docs, state, and legacy migration.
- `runtime/runtime_ops.py` - user-level Codex runtime, agents, skills, platform
  settings.
- `runtime/platform_settings.py` - Codex `config.toml` patching, including the
  orchestrator model.
- `runtime/release.py` - semver and GitHub Release acquisition.
- `runtime/transaction.py`, `runtime/backup.py`, `runtime/plan.py` - mutation,
  backup, and transaction primitives.
- `runtime/layout.py`, `runtime/markers.py` - path and marker contracts.

## Main Interfaces and Integration Boundaries

- CLI: `vision --install`, `--update`, `--check-update`,
  `--config orch sol|luna`, `--config <role> <provider/model#variant>`,
  `--remove`, with `--platform codex|opencode|both`.
- Runtime: `python3 <client-home>/vision/runtime/workflow.py <command>`.
- GitHub Releases: universal `vision-<version>.zip` plus `SHA256SUMS`.
- Codex integration: `~/.codex/AGENTS.md`, `config.toml`, `agents/`, `skills/`
  (including native `$vision-*` command skills).
- OpenCode integration: `~/.config/opencode/AGENTS.md`, `agents/`, `skills/`,
  `commands/` (native `/light`, `/medium`, `/heavy`, and lifecycle commands);
  provider auth and main-session model remain OpenCode-owned.

## Tests and Supporting Assets

- `scripts/test_workflow_runtime.py` - lifecycle, platform, and package
  regression tests.
- `scripts/test_deployment_token_report.py` - Codex and OpenCode token report
  tests.
- `scripts/sync_workers.py` - regenerate Codex TOMLs from canonical workers.
- `python -B vision/runtime/workflow.py validate --package-root vision`.
