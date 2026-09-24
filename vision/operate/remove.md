# Remove vision

Run this procedure only for the exact command:

    vision --remove

Treat this as a destructive operation. Use two phases: first produce a read-only
plan, then allow execution only after one clear second confirmation from the
user. Do not ask any other questions.

First run the lifecycle CLI without `--confirm`:

```text
python3 {{VISION_HOME}}/runtime/workflow.py \
  remove --project <project> --json
```

Use the equivalent `py -3.11` invocation and native paths on Windows. Pass
`--platform codex|opencode|both` to select which client installation to remove.
Report the plan and explicitly warn that the confirmed phase will permanently
delete Vision-owned resources for the selected client(s):

- project workflow state and legacy hidden workflow resources;
- the workflow-managed region in the client's user-level `AGENTS.md` (the user
  file itself is deleted only when no unrelated content remains);
- workflow-owned keys in the Codex config, when Codex is selected;
- generated worker files carrying a matching `vision-worker` ownership marker;
- skill directories tracked by installation state and carrying a matching
  `vision-skill` ownership marker;
- every file under `{{VISION_HOME}}/`, including source and update backups.

Also report that a legacy project wrapper, if present, is removed while its
project-specific instructions are restored to the native root `AGENTS.md`, and
that workflow-owned marked `.gitignore` rules are removed. Native project
`AGENTS.md`, `agent_docs/`, unrelated user-level AGENTS/config content,
unrelated worker files, and unrelated skills are preserved. Do not claim that
anything has been removed during this first phase.

Then ask exactly one confirmation, for example:

    This will permanently remove vision and its workflow-owned files. Confirm removal? (yes/no)

If the reply is not an explicit affirmative, stop without running the second
phase. After an affirmative reply, run:

```text
python3 {{VISION_HOME}}/runtime/workflow.py \
  remove --project <project> --confirm --json
```

Report the final JSON result. If the command fails, reports an error, or rolls
back, do not describe the removal as successful.
