# Model Configuration

Supported command forms:

    vision --config orch sol|luna
    vision --config senior sol|luna

Use Python 3.11 or newer. Change the orchestrator (main-agent), Senior Executor,
or an OpenCode worker-role model with the lifecycle CLI. `sol` selects the Sol
model; `luna` selects the Luna model. Use `luna` for both orchestrator and Senior
Executor to run an all-Luna workflow.

The default Codex target for both keys is `sol`. Switching a model preserves that
role's reasoning effort: the orchestrator keeps its effort in the Codex config,
and the Senior Executor keeps its original `medium` effort in its worker file.

For OpenCode, use a native model ID of the form `provider/model` or
`provider/model#variant`, for example `anthropic/claude-sonnet-4-5#high` or
`openai/gpt-5.1-codex`. It also accepts these worker-role keys, which regenerate
that role's OpenCode agent file from Vision-owned configuration:

    vision --config explorer|investigator|default_executor|senior_executor|tester|archivist <model>

The OpenCode main/orchestrator model is normally owned by OpenCode itself and is
not forcibly overwritten by Vision.

## Apply

Run:

```text
python3 {{VISION_HOME}}/runtime/workflow.py config --key <orch|senior|worker-role> --value <sol|luna|model-id> --json
```

On Windows use the equivalent `py -3.11` invocation and native paths. Pass
`--platform codex|opencode|both` to select the client when more than one Vision
installation is present.

- Codex `--key orch` sets the top-level `model` and records the choice under the
  workflow-owned `[vision]` section; `--key senior` sets the Senior Executor's
  worker model and records the choice.
- OpenCode `--key senior` and the worker-role keys store the mapping in
  Vision-owned configuration and regenerate the affected `agents/*.md` files.
  Do not edit generated agent files by hand.

Recorded choices are reapplied on later installs and updates, and unrelated
client settings are preserved. The change applies to new sessions; restart your
client if the model does not switch immediately.

Report the selected platform, key, target, model written, whether the config
changed, and any failure. Do not describe a failed or rolled-back change as
successful.
