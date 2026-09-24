# vision 1.1.14 — Experimental release notes

## Overview

Version 1.1.14 combines the flexible orchestration introduced in 1.1.13 with
guidance intended to reduce main-agent rollouts and repeated context costs.
It also unifies documentation and deployment handoff work under Archivist and
reorganizes the lifecycle files.

The main agent retains task direction, architecture, worker selection,
dependencies, acceptance, and final claims. Batching is scheduling guidance
that adapts to the task. This release does not claim a measured cost reduction;
the effect still needs to be evaluated in representative deployments.

## Orchestration and context

- Medium and Heavy recommend dispatching independent workers that inform the
  same decision together, waiting for the relevant results, and synthesizing
  them once. Independent main-owned reads and checks can share a bounded call.
- Dependencies, overlapping mutable state, and uncertainty still determine
  where sequential work is appropriate.
- Heavy leaves routine operational checks and ordinary repair with responsible
  workers. Main evaluates evidence and intervenes for material decisions.
- Companion is created when a bounded context assignment justifies the
  dispatch. It can retain project knowledge across assignments and route
  changes. Related questions should be combined when practical.
- Companion handles the available project ecosystem; Investigator handles
  bounded questions requiring Internet research.
- Role-specific task capsules retain Task ID, context, task/goal, and the
  main agent's relevant knowledge and guidance. Follow-ups carry the delta.
- The complete project documentation framework is read at the first
  deployment-state entry in a session and reused across Medium and Heavy.

## Worker reports

Intermediate updates are reserved for evidence that changes a main-owned
decision. Report budgets are explicit in worker TOMLs:

| Role | Intermediate update | Routine report | Material escalation |
| --- | ---: | ---: | ---: |
| Default / Senior Executor | 100 words | 120 words | 200 words |
| Tester | 100 words | 120 words | 200 words |
| Investigator | 100 words | 120 words | 180 words |
| Companion | 100 words | 220 words per assignment | Within assignment budget |
| Archivist | 80 words | 120 words | 200 words |

Archivist closure reports allow up to 200 words of prose plus the verbatim
Deployment Token Report table. Workers retain detailed supporting evidence and
return references, findings, limitations, and decisions needed by the main.

## Archivist

`archivist` replaces `doc-writer` and `closure_steward`. The built-in worker set
is now `default_executor`, `senior_executor`, `tester`, `companion`,
`investigator`, and `archivist`. Archivist uses Luna with xhigh reasoning.

Archivist owns assigned public and project documentation, including overview,
structure, core technologies, module documents, progress, and latest-session
handoff records. The main agent directly owns deployment updates to
`agent_docs/project_diary.md`.

Both Medium and Heavy can use Archivist. Medium continues to keep production
implementation and verification with the main. Bootstrap/install assigns
Archivist the initialization of listed new or template-marked framework files,
including the diary scaffold when listed, while preserving healthy documents.

The main can combine remaining verified documentation updates and closure in
one assignment, reuse an informed Archivist, or create one with a finite
recent-context fork. Each substantive deployment has one closure reporting
owner. Concurrent documentation assignments require distinct write scopes.

Archivist records complete, paused, or blocked state and a recoverable next
entry point. Git reporting remains read-only; production changes, tests,
acceptance decisions, and Git mutations are outside the role's ownership.
Shared assignment guidance lives in `archivist.md`.

## Deployment Token Report

The main agent places the deployment boundary in its own commentary:

```text
<!-- vision-deployment-start: <deployment_id> -->
```

Reporting no longer requires a Companion assignment to hold that marker.
After finishing assigned documentation and closing checks, Archivist invokes
the reporting skill. The parser identifies its parent main-agent session and
finds the matching marker there.

The table preserves the six columns `Agent`, `Quantity`, `Rollouts`,
`Cached input`, `Input`, and `Output`. Input includes its cached subset.
Totals stop when reporting starts and exclude the subsequent Archivist and
main-agent final responses. Missing evidence is reported rather than estimated.
Ordinary documentation assignments and direct-fast-path tasks do not invoke
deployment reporting.

## Package layout and upgrade instructions

Lifecycle guides and metadata now live under `vision/operate/`:
`bootstrap.md`, `check_update.md`, `disable.md`, `enable.md`, `install.md`,
`personalization_guide.md`, `remove.md`, `update.md`, `VERSION`, and
`user_AGENTS.md`.

The executable entry point is `vision/runtime/workflow.py`. Command
guides, package validation, release automation, and fixtures use the new paths.
User-facing command prompts remain unchanged.

**Upgrading from 1.1.13 or another root-layout installation requires the incoming
launcher.** The old launcher expects root-level version metadata and cannot
discover this package layout. After downloading, verifying, and extracting the
1.1.14 ZIP, run from the target project:

```sh
python3 <extracted>/vision/runtime/workflow.py update \
  --source <extracted>/vision --project <project> --json
```

Use Python 3.11 or newer and native platform paths; on Windows use the equivalent
`py -3.11` command. Review the bundled `operate/update.md` before upgrading.
The incoming runtime reads historical package layouts, preserves project
documents, personalization and unrelated settings, backs up the update, and
removes obsolete workflow-owned files and worker definitions. Restart Codex
after upgrading to load the new worker definitions and command instructions.

## Artifact and validation

- Artifact: `dist/vision-1.1.14.zip`.
- SHA-256: `56951c3f8436cb595fb5b2d94764b015864cd6c66f4381418d653b78ab649ac4`.
- The supplied rebuilt ZIP passed checksum and package/archive validation.
- Every packaged file matched the current source, with no extra or missing files.
- Automated test suites were not run during this commit preparation, per the
  user's instruction. Package validation does not establish runtime regression
  coverage or measured orchestration performance.
