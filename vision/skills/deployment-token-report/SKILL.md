---
name: deployment-token-report
description: Compile per-agent rollout counts and cached-input, input, and output token totals from the deployment's native session records after a substantive workflow deployment. Use only for the workflow's required post-deployment usage handoff, not for direct-fast-path work or live cost estimation.
---

# Deployment Token Report

<!-- vision-skill: deployment-token-report -->

Use this skill only as Archivist for an assigned deployment closure, after all
assigned documentation updates, compact checks, and Git inspection are complete.
Treat that closure state as sealed;
the repository and closure evidence remain unchanged after reporting starts.

Use the supplied deployment ID unchanged. It must match
`[a-z0-9][a-z0-9_-]{0,63}` and the main agent's deployment marker:

```text
<!-- vision-deployment-start: <deployment_id> -->
```

Run the bundled `scripts/report_tokens.py` with `--deployment-id` and
`--format markdown`. Pass `--platform codex` or `--platform opencode` to select
the native backend; the default is Codex.

- The Codex backend uses `CODEX_THREAD_ID` to identify this Archivist rollout,
  resolve its parent main-agent thread, find the exact marker in the
  assistant message text there, and read only metadata and token-count fields
  beneath `~/.codex/sessions/`. Accept the marker when surrounded by Markdown or
  explanatory prose. Exclude guardian sessions.
- The OpenCode backend uses the native session list and export interfaces to
  identify the main session, its child/subagent sessions, model, and token
  usage. Provide `--caller-session-id` (or `OPENCODE_SESSION_ID`) for the
  Archivist child session.

Return only the script's six-column Markdown table verbatim to the main agent,
with no pricing, estimates, inferred usage, or additional statistics. Treat a
script failure or incomplete-evidence warning as the report result and return
the limitation verbatim. In the Codex backend, stop totals when the script
starts, excluding Archivist's post-tool final response and the main agent's
later final response.

The required table template is exactly:

```text
| Agent | Quantity | Rollouts | Cached input | Input | Output |
| --- | ---: | ---: | ---: | ---: | ---: |
| <agent role> | <count> | <count> | <tokens> | <tokens> | <tokens> |
```

Keep the columns exactly as shown and preserve every data row emitted by the
script, including its final `main agent` row.

Interpret `Input` as total input tokens, including the cached-input subset, and
`Rollouts` as model generations with a usage record.
