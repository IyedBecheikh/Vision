# Workflow Update

Supported command forms:

    vision --update

Use Python 3.11 or newer. Apply the validated update directly with the lifecycle
CLI.

## Source

Use the script to query GitHub Releases and select the highest non-draft SemVer
release containing both the universal ZIP and `SHA256SUMS`. Include prereleases
and never clone the repository. For a different version, verify the checksum,
extract the ZIP safely, and let the installed launcher delegate planning and
application to the incoming CLI, which validates its package schema. When the
selected version matches the installed user-level version, use the installed
source to update the current project without downloading the ZIP again.

## Update

Run:

```text
python3 {{VISION_HOME}}/runtime/workflow.py update --project <project>
```

Pass `--platform codex|opencode|both` to update every recorded platform; omit it
to update the installed client(s). When the installed package still stores
`VERSION` at its root, run the incoming package's `runtime/workflow.py` instead
of the installed launcher. The incoming runtime recognizes that historical
layout and migrates it transactionally.

For a newer release, let the script replace installed routes, worker files, and
workflow-owned skills with the incoming release's fixed definitions. For Codex,
expect it to set the workflow-owned `[features.multi_agent_v2]` values in
`~/.codex/config.toml` to `enabled = true`, `min_wait_timeout_ms = 300000`,
`default_wait_timeout_ms = 300000`, and `max_wait_timeout_ms = 1800000`. For
OpenCode, expect it to regenerate the native `agents/*.md` subagents while
preserving Vision-owned worker-model mappings in `config.json`.
Expect it to preserve unrelated client settings and skills, project documents,
native project instructions, and source backups. For a project still using an
older workflow wrapper, expect the script to validate its managed region
against that version's source backup, remove the wrapper, and restore its
personalization and project-local regions as ordinary project `AGENTS.md`
content. Expect it to remove obsolete workflow-owned files and retired
workflow-owned `AGENTS.md` and `agent_docs/` `.gitignore` rules, create a
verified timestamped backup, and apply user/project state through one
compensating transaction.
Preserve an `agent_docs/` ignore rule that the user owns outside the
workflow-managed block.

When the user-level workflow already matches the selected release, expect a
project-only update. It migrates a legacy wrapper when present, updates project
workflow state, and saves a backup only for changed existing files. It leaves
native project instructions and installed user-level definitions unchanged. If
the project is already current, expect an explicit no-op with no new backup.
Run the command separately in each installed project.

If a legacy project entry point contains merged local edits, or the protected
project-local region references missing legacy route files, expect the update
to stop. Review and extract only genuine project-local instructions into a
temporary file, then rerun with:

```text
--legacy-local-instructions <reviewed-file>
```

Treat this as a one-time migration into the dedicated local region. Never infer
the content automatically. Add `--allow-downgrade` for a downgrade.

Report the installed version, the project result, backup location when one was
created, and any failure.
Do not describe a partial or rolled-back update as successful.
