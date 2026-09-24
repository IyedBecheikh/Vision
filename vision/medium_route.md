# Medium Route

Use after Medium is selected under `AGENTS.md`.

## Main Ownership

The main agent owns planning, root-cause reasoning, implementation,
production repair, verification, integration, acceptance, final claims, and user
communication. Medium does not delegate production or verification.

Optimize for fewer main-agent decision turns and lower main-agent context
consumption while preserving quality and completion. Aggregate support-worker
token use is not the optimization target.

Use only these support roles:

| Role | Ownership |
| --- | --- |
| Explorer | One of two disposable read-only workers mapping the same bounded project-context task from complementary angles. |
| Investigator | One of three disposable read-only workers researching the same bounded problem from distinct search angles. Each can propose options; the main makes every project decision. |
| Archivist | The required substantive-deployment closure worker defined by `{{VISION_HOME}}/archivist.md`. It owns concise assigned documentation outside the main-owned deployment-state documents, read-only Git reporting, and the closing Deployment Token Report. |

## Shared Deployment-State Entry

Before route-specific planning or execution, complete the shared `agent_docs/`
intake in `AGENTS.md`. Do not repeat it after a route change.

## Context Routing After Intake

After the shared intake and before broader source discovery or planning, use
`agent_docs/` to create a compact working-context map:

- **Direct**: code, contracts, interfaces, and evidence the main must inspect to
  own diagnosis, implementation, verification, integration, risk, or acceptance.
- **Explorer**: bounded context discovery, supporting modules, tools,
  configuration, logs, dependencies, document deltas, and evidence retrieval.
- **Investigator**: bounded fault hypotheses, solution research, alternatives,
  feasibility, technical comparisons, or prior art using project or Internet sources.

Keep this map in working state, not durable documentation, and revise it only
when material evidence changes relevance. Directly inspect a delegated surface
when it becomes necessary for main-owned production or a material decision.
Dispatch Explorer pairs or Investigator trios together when useful.

## Deployment Boundary

Follow the deployment-boundary rule in `AGENTS.md`. Keep its ID for Archivist's
closure report.

## Support Packages and Investigation

Start each initial support package with **Task ID**, a logical identifier unique
within the deployment, followed by the capsule for that role:

| Role | Capsule parts |
| --- | --- |
| Explorer | **Exploration ID**; **Exploration Context**; **Exploration Task + Goal**; **Main-Agent Exploration Guidance** |
| Investigator | **Problem ID**; **Solution Context**; **Solution Search Task + Goal**; **Main-Agent Solution Guidance** |
| Archivist | **Documentation Context + Audience**; **Documentation Task + Goal**; **Main-Agent Documentation Guidance** |

Treat these parts as the complete structure. Include only material context,
references, boundaries, intended outcomes, main-owned decisions, constraints,
and cautions. Require Task ID in every report. Follow-ups repeat it and send
only changed capsule parts.

The main retains interpretation, root-cause reasoning, and every project
decision because it holds the decisive project context. Use Explorer for
bounded context work and Investigator for solution research. Both return
evidence, unknowns, and implications; neither owns causal, architecture,
implementation, or acceptance decisions.

For one bounded context task that needs Explorer, start exactly two Explorers
in the same dispatch. Give them one shared Exploration ID and context question,
distinct Task IDs, and complementary discovery angles in each lane's
**Exploration Task + Goal**. Each lane maps the full bounded task; its angle guides evidence
collection. Keep the lanes independent. Wait for both reports, compare evidence
and gaps, then make the main-owned decision. If a lane fails, retry or replace
only that lane; if replacement is unavailable, report the limitation.

For one bounded problem that needs Investigator, start exactly three
Investigators in the same dispatch. Give them one shared Problem ID and problem
statement, distinct Task IDs, and complementary search angles in their Solution
Search Task + Goal. Choose angles suited to the problem: different hypotheses,
solution approaches, evidence sources, or a challenge to likely assumptions.
Each lane seeks an answer to the full problem; its angle guides the search.
Keep their searches independent. Wait for all three reports, compare evidence
and disagreements rather than voting, then make the main-owned decision. If a
lane fails, retry or replace that lane without rerunning completed lanes; do
not treat an incomplete trio as a complete search. If replacement is unavailable,
report the limitation with the available evidence.

## Rollout-Efficient Support

- Batch independent main-owned reads, searches, metadata checks, and tool
  operations into bounded calls.
- When several support workers inform one decision, dispatch them together,
  wait for the relevant set, and synthesize once. Start another batch only when
  existing evidence materially changes the questions.
- Do not poll support workers, request status-only updates, inspect activity
  files, or repeatedly request available evidence. Use lifecycle events,
  appropriately long waits, and `list_agents` only for genuine terminal-state
  uncertainty.
- Keep dependent or overlapping main-owned changes sequential and verification
  proportionate to risk. Never weaken validation or claim an unrun check passed.

## Fixed Boundaries

- Medium has no workflow-imposed aggregate active-subagent limit.
- Limit Medium workers to Explorer, Investigator, and Archivist.
- Give support workers bounded questions and sufficient context; retain every
  material interpretation and final claim in the main.
- Archivist owns assigned documentation outside `project_progress.md`,
  `project_diary.md`, and `latest_session_work.md`, plus closure reporting. Keep
  those three documents, implementation, production repair, root-cause
  decisions, and verification with the main.
- Preserve unrelated work and keep Git mutations within explicit authority.

## Fast Path and Closure

Use the worker-free direct fast path only when the complete request is a question
or small bounded leaf task. Do not initialize deployment state merely because
Medium remains selected.

Before the final response that completes, pauses, or blocks a substantive
deployment, update `agent_docs/project_progress.md`,
`agent_docs/project_diary.md`, and `agent_docs/latest_session_work.md` yourself,
keeping them concise and canonical. Then follow
`{{VISION_HOME}}/archivist.md` exactly once. Combine any other verified
documentation updates with its required closure assignment when practical.
Relay its handoff and exact six-column `$deployment-token-report` table. Use a
new deployment ID for each later deployment.
