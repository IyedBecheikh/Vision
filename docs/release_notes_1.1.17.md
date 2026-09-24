# vision 1.1.17 — Minor fixes with no performance impact

Version 1.1.17 corrects documentation ownership and worker-facing descriptions.
These are instruction-quality fixes and do not change models, reasoning effort,
execution topology, context limits, or expected performance.

## Document scope adjustment

The main agent now handles `agent_docs/project_progress.md` and
`agent_docs/latest_session_work.md` alongside `project_diary.md`. Archivist uses
these documents as canonical closure inputs but does not edit them during a
deployment. The generated document templates now contain only project state,
not embedded maintenance instructions.

## Consistent Archivist usage in Medium

Medium-route descriptions now consistently state that Archivist is used for
every substantive deployment closure. Medium still keeps implementation,
repair, root-cause decisions, and verification with the main agent. Archivist
handles other assigned documentation, the read-only Git handoff, and the
Deployment Token Report.

## Worker-perspective instructions

Archivist installation and closure instructions now explain the observable
assignment context, supplied inputs, required task, and applicable authority
from Archivist's perspective. Companion's initial assignment uses the same
worker-facing approach, avoiding designer-facing lifecycle assumptions and
hidden context.

## Validation and artifact

- Artifact: `vision-1.1.17.zip`.
- SHA-256: `d9300d43a78058e1d2acab6c1f849f1c47e48f21d227e4243f9357a850bfdbcc`.
- Validation passed: 58 runtime tests, 8 Deployment Token Report tests,
  package-schema validation, and independent archive verification.
