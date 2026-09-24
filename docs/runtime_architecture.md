# Lifecycle Runtime Architecture

The lifecycle runtime separates fixed release definitions, installation state,
generated outputs, and project-owned content.

## Data ownership

- Route documents and worker subagents: authoritative behavior distributed by a
  release.
- Canonical worker instructions: `vision/workers/<role>.md`, one body per role.
  Platform renderers turn that body into Codex TOML (`vision/agents/<role>.toml`)
  or OpenCode Markdown (`agents/<role>.md`), so the clients cannot drift.
- `~/.codex/vision/` and `~/.config/opencode/vision/`: per-platform user command
  guides, the user-level instruction source, and package version metadata.
- `install_state.json`: installed version, selected platforms, and ownership
  manifests, written per platform.
- Heavy and Archivist contracts: fixed release inputs copied unchanged.
- Worker files and workflow-owned platform settings: materialized outputs.
- Native commands: one canonical mapping rendered as Codex skills
  (`~/.codex/skills/vision-*/`) or OpenCode slash commands
  (`~/.config/opencode/commands/*.md`), owned and refreshed per platform.
- User-level `AGENTS.md`: one marked workflow region containing route,
  documentation, rollout, and lifecycle-command policy in each client.
- Project `AGENTS.md`: native project-owned personalization, never generated or
  wrapped by the current workflow.
- Project documentation updates during deployment: main owns `project_progress.md`,
  `project_diary.md`, and `latest_session_work.md`; Archivist owns other
  assigned public and project documents plus the closing read-only Git handoff
  and deployment token report. An installer-assigned Archivist may initialize
  new or still-template versions of the three state documents.

## Module boundaries

- `layout.py`: package and Codex target path contracts.
- `platform_settings.py`: fixed workflow-owned Codex TOML keys.
- `platforms/base.py`: shared platform contract (`runtime_paths`,
  `install_global_instructions`, `render_worker`, `install_worker`,
  `install_skill`, `patch_platform_config`, `remove_owned_resources`,
  `collect_session_usage`).
- `platforms/codex.py`: Codex backend, reproducing existing behavior.
- `platforms/opencode.py`: OpenCode backend (native Markdown subagents,
  permissions, and ownership).
- `workers.py`: canonical worker store loader and Codex renderer.
- `commands.py`: canonical native command mapping and Codex/OpenCode renderers.
- `platform_lifecycle.py`: platform-aware bootstrap/update/remove/config
  composition for `codex`, `opencode`, and `both`.
- `session_usage.py`: platform-neutral dispatch to the token-report backend.
- `markers.py`: user-region handling, legacy project-wrapper parsing, and the
  `{{VISION_HOME}}` platform-resolved placeholder.
- `project_ops.py`: project state, documents, ignore rules, and legacy-wrapper
  migration.
- `runtime_ops.py`: user-level Codex runtime and generated outputs.
- `backup.py`: persistent update backups.
- `transaction.py`: atomic file writes and compensating rollback.
- `plan.py`: validated mutation plans and compact summaries.
- `lifecycle.py`: Codex plan composition only; it owns no low-level
  transformation.
- `release.py`: release selection, checksum, and safe extraction.
- `runtime/workflow.py`: CLI parsing, direct application, two-phase removal,
  platform selection, and incoming-runtime delegation.

The removal plan preserves native project `AGENTS.md`, deletes private workflow
state, strips only the marked workflow region from each selected client's
user-level `AGENTS.md`, removes workflow-owned Codex settings and worker files,
and cleans the dedicated runtime directory. A legacy wrapped project entry is
first restored to ordinary project instructions. `agent_docs/`, unrelated
user-level content, and unrelated OpenCode agents/skills/config remain.

## Upgrade contract

1. The installed launcher selects and safely acquires the incoming release.
2. The incoming CLI validates and applies the update using the target
   version's runtime; the installed launcher does not apply its own
   version-specific package schema to that incoming release.
3. The incoming release replaces installed routes and worker definitions.
   Worker surfaces are copied from the incoming role files.
4. Native project instructions are not part of the update surface. A legacy
   workflow-owned project wrapper is validated against its recorded source,
   then its personalization and local regions become ordinary `AGENTS.md`
   content.
5. Legacy marker drift or ambiguous legacy content stops before live writes.
6. Every write command validates and applies one mutation plan with rollback.

Changing built-in behavior requires updating its owning route, worker, or
platform module and the corresponding tests; installed retuning is unsupported.
