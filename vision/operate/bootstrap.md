# Initial Workflow Bootstrap

Use this guide only for the first installation from a universal GitHub Release
ZIP. Use Python 3.11 or newer. On Windows, use the equivalent `py -3.11`
invocation and native paths.

Verify `vision-<version>.zip` against `SHA256SUMS`, extract it into a
temporary directory, and require exactly one top-level `vision/`
directory. Then validate the package:

```text
python3 vision/runtime/workflow.py validate --package-root vision --json
```

Stop on any validation error. From the project being bootstrapped, run:

```text
python3 <extracted>/vision/runtime/workflow.py bootstrap \
  --package-root <extracted>/vision \
  --project <project> \
  --platform codex|opencode|both
```

Pass `--platform` to install Vision for the Codex client, the OpenCode client,
or both. When it is omitted and more than one supported client is detected, the
CLI prompts for a choice; otherwise it installs for the detected client.

Expect the bootstrap to install the shared runtime, source backup, merged
user-level workflow instructions, installation state, generated worker
subagents, and workflow-owned skills for each selected platform. Expect it to
initialize the current project's documentation scaffold, workflow state, and
hidden resource ignore rule without creating, wrapping, or changing a native
project `AGENTS.md`. A legacy workflow-owned wrapper is migrated back to
ordinary project instructions in the same compensating transaction. For Codex,
the generated config enables multi-agent tools and writes
`[features.multi_agent_v2]` with `enabled = true`,
`min_wait_timeout_ms = 300000`, `default_wait_timeout_ms = 300000`, and
`max_wait_timeout_ms = 1800000` while preserving unrelated settings. OpenCode
owns its own provider, credential, and main-model configuration, and Vision
only adds per-role agent files.

## Required documentation action

Read the command's `agent_actions` result. Expect one required `archivist`
action for the Project Documentation Framework. Spawn the `archivist` subagent
(in Codex with `agent_type="archivist"`, `task_name="bootstrap_docs"`, and
`fork_turns="none"`; in OpenCode as the native `archivist` subagent). Use Task ID
`bootstrap_docs` and the Documentation Context +
Audience, Documentation Task + Goal, and Main-Agent Documentation Guidance
capsule. Include the project root and returned
`files`, `created_files`, `recovery_files`, `framework`, and
`required_context_files` lists, with these requirements:

- Inspect only enough project evidence to record verified initial context;
  source-less projects are valid.
- Initialize only documents listed in `files`—newly created or
  still-template-marked recovery documents—and remove their
  `vision-bootstrap-template` markers.
- Populate listed `project_structure.md`, `project_overview.md`, and
  `project_core_tech.md` recovery or new files with verified project structure,
  purpose/architecture, and technology context. If relevant source is absent,
  explicitly record that fact instead of leaving template-only content.
- Preserve every pre-existing project document not listed for recovery. If
  `files` is empty, perform a read-only completeness check of all documents in
  `framework`.
- For this installation action only, initialize listed new or recovery
  `project_progress.md`, `project_diary.md`, and `latest_session_work.md` files;
  later deployment updates belong to the main. Leave deployment status empty
  when no plan exists.
- Do not edit source, project `AGENTS.md`, Git state, or user-level files.

Verify that every framework file exists, no file listed in `files` retains the
bootstrap marker, and every listed file in `required_context_files` has been
populated. Treat installation as incomplete if the required worker cannot run
or fails; do not silently perform its work in the main thread.

Restart your client only after the bootstrap and required documentation action
both succeed.
