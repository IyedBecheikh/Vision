# Workflow Installation

Use this procedure only to install the already-bootstrapped workflow into the
current project. Do not manually copy or merge workflow files, and do not
modify or reinstall anything under the selected client's `vision/` directory.

Use Python 3.11 or newer. On Windows, use the equivalent `py -3.11` invocation
and native paths.

## Existing project installation

Let the CLI use project state, not the presence of `AGENTS.md`, to recognize an
existing installation. It may repair stale state, the workflow-owned
`.gitignore` block, leftover package staging, or missing and still-template
documentation. If any framework document needs initialization or recovery,
complete the returned documentation action below. Accept an empty `files` list
when only non-document repairs are applied. Treat `already installed` as a
healthy no-op.

The project `AGENTS.md` is project-owned. Installation must preserve it exactly.
If a legacy workflow-owned wrapper is present, expect the CLI to validate and
remove the wrapper while restoring its personalization and project-local regions
as ordinary project instructions. Stop on malformed, drifted, or conflicting
legacy entry points and report the recovery instruction.

## Install the current project

Use the installed CLI:

```text
python3 {{VISION_HOME}}/runtime/workflow.py install \
  --project <project>
```

Pass `--platform codex|opencode|both` to select which installed client(s) the
project should track. Use the command to read templates from the existing
user-level bootstrap and
change only the current project. Expect it to create missing files in the
`agent_docs/` scaffold, workflow state, and other project-level assets. Preserve
the native project `AGENTS.md` and unrelated `.gitignore` rules. The marked
workflow-owned block ignores only `.vision_hidden_resources/`; it must
not ignore `AGENTS.md` or `agent_docs/`.

Keep the shared user-level runtime, fixed definitions, user instructions,
source backup, and worker files unchanged. Stop and report the
error if the initial user-level bootstrap is missing.

## Required documentation action

For every new installation or documentation-recovery result, run the required
`archivist` action. Skip it for a healthy `already installed` no-op. Spawn the
returned action (in Codex with
`agent_type="archivist"`, `task_name="install_docs"`, and
`fork_turns="none"`; in OpenCode as the native `archivist` subagent). Use Task ID
`install_docs` and the Documentation Context +
Audience, Documentation Task + Goal, and Main-Agent Documentation Guidance
capsule. Pass the project root and returned `files`, `created_files`,
`recovery_files`, `framework`, and `required_context_files` lists. Initialize
only documents in `files`: these are newly created or still-template-marked
recovery documents. Remove their bootstrap markers and preserve every other
existing document. Populate listed `project_structure.md`, `project_overview.md`,
and `project_core_tech.md` files with verified project evidence. If the project
is empty, pause before spawning Archivist and ask the user to provide either a
concise project overview in the conversation or a path to an overview document.
If the user provides a path, read that document as the initial project-context
source and include the path and its verified contents in Archivist's capsule;
do not scan unrelated files or invent missing context. Treat installation as
incomplete and report the blocker if the user provides neither form of
overview. If `files` is empty, perform only a read-only framework completeness
check.
For this installation action only, Archivist may initialize listed new or
recovery `project_progress.md`, `project_diary.md`, and
`latest_session_work.md` files; later deployment updates belong to the main.

Treat installation as incomplete if the required worker cannot run or fails.
Do not silently perform its work in the main thread.
