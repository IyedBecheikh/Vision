# Project Overview

## Purpose

Vision is a token-efficient multi-agent orchestration workflow for the Codex
CLI/Codex app and OpenCode. It provides route selection, durable project memory
(`agent_docs/`), bounded worker delegation, and a deterministic Python lifecycle
CLI. Vision is a rebranded fork of the original `codex_workflow` project by
viettran-edgeAI, extended with shared/orchestrator/subagent agent instructions,
an orchestrator-model configuration command, and a platform abstraction so one
workflow runs natively on both Codex and OpenCode.

## Scope

- Workflow instructions, routes, and worker definitions installed under the
  selected client configuration and per project.
- A standard-library Python runtime for install, update, remove, check-update,
  platform selection, and model configuration lifecycle operations.
- One canonical worker instruction body per role, rendered to Codex TOML or
  OpenCode Markdown by a platform adapter.
- One canonical native command mapping rendered to Codex `$vision-*` skills or
  OpenCode slash commands, installing both for `--platform both`.
- A one-time bootstrap from a universal GitHub Release ZIP.
- Not a Codex or OpenCode plugin, model, or provider; it configures multi-agent
  usage for the selected client.

## Architecture

- Package source lives in `vision/`, versioned by `vision/operate/VERSION`.
- Canonical worker instructions live in `vision/workers/`; platform renderers
  produce Codex TOMLs and OpenCode Markdown subagents.
- The Codex backend installs the runtime to `~/.codex/vision/`, worker TOMLs to
  `~/.codex/agents/`, the workflow skill to `~/.codex/skills/`, and the managed
  policy region to `~/.codex/AGENTS.md`.
- The OpenCode backend installs the runtime to `~/.config/opencode/vision/`,
  native Markdown subagents to `~/.config/opencode/agents/`, the skill to
  `~/.config/opencode/skills/`, and the managed policy region to
  `~/.config/opencode/AGENTS.md`.
- Each project gets `agent_docs/`, workflow state under
  `.vision_hidden_resources/`, and a managed `.gitignore` block.
- The lifecycle runtime plans mutations first and applies them as one
  compensating filesystem transaction; `--platform codex|opencode|both` selects
  which client installations are touched.

## Main Workflows

- Light route: direct work without subagents (default).
- Medium route: read-only Explorer/Investigator/Archivist support; main owns
  implementation and verification.
- Heavy route: delegated Executors/Testers plus read-only discovery; main owns
  orchestration, synthesis, and acceptance.

## Major Decisions

- Rebrand `codex_workflow` to `vision` throughout markers, paths, commands, and
  release assets while preserving the original runtime architecture.
- Keep the worker model split: Luna workers with a Sol Senior Executor by
  default, while allowing an all-Luna workflow via `vision --config orch luna`.
