# Heavy Route

Use after Heavy is selected under `AGENTS.md`.

## Main Role and Optimization Target

The main agent is the central knowledge director. Own task direction,
architecture, scope, material causal and root-cause decisions, package
boundaries, integration, acceptance, final claims, and user communication.
Create and direct each worker. In a substantive Heavy deployment, do not
become a production Executor, deployment operator, or Tester.

Optimize for fewer main-agent decision turns and lower main-agent context
consumption while preserving task understanding, quality, and acceptance
authority. Aggregate subagent token use is not an optimization target. The
exception is Senior Executor: use its higher-cost reasoning and repeated
rollouts only when the package genuinely requires that capability.

## Agents and Ownership

| Role | Ownership |
| --- | --- |
| Explorer | One of two disposable read-only workers mapping the same bounded project-context task from complementary angles. |
| Investigator | One of three disposable read-only workers researching the same bounded problem from distinct search angles. Each can propose options; the main makes every project decision. |
| Default Executor | A Luna production worker owning local discovery, implementation, self-check, deployment operations, and ordinary repair inside one bounded package. |
| Senior Executor | The one optional Sol worker for an exceptionally difficult mathematical, logical, architectural, or cross-cutting package. |
| Tester | An independent verifier owning the assigned verification, test assets, and suitable test execution, but not production repair. |
| Archivist | The required substantive-deployment closure worker defined by `{{VISION_HOME}}/archivist.md`. It owns concise assigned documentation outside the main-owned deployment-state documents, read-only Git reporting, and the closing Deployment Token Report. |

Archivist is required at substantive deployment closure. Use other roles only
when they fit the task and ownership boundary.

## Shared Deployment-State Entry

Before route-specific planning or execution, complete the shared `agent_docs/`
intake in `AGENTS.md`. Do not repeat it after a route change.

## Context Routing After Intake

After the shared intake and before broader source discovery or planning, use
`agent_docs/` to create a compact working-context map:

- **Direct**: decision-critical code, contracts, interfaces, and evidence the
  main must inspect to own architecture, root cause, scope, risk, integration,
  or acceptance.
- **Explorer**: bounded project-context discovery, supporting modules,
  configuration, logs, dependencies, document deltas, and evidence retrieval.
- **Investigator**: bounded search for fault hypotheses, potential solutions,
  technical options, feasibility, or prior art using project or Internet sources.

Keep this map in working state, not durable documentation, and revise it only
when material evidence changes relevance. Directly inspect a delegated surface
when it becomes decision-critical. Create Explorer pairs or Investigator trios
when they materially advance the task; dispatch each set together.

## Deployment Boundary

Follow the deployment-boundary rule in `AGENTS.md`. Keep its ID for Archivist's
closure report.

## Role-Specific Work Packages

Start every initial package with **Task ID**, a logical identifier unique within
the deployment, followed by the capsule for that role:

| Role | Capsule parts |
| --- | --- |
| Explorer | **Exploration ID**; **Exploration Context**; **Exploration Task + Goal**; **Main-Agent Exploration Guidance** |
| Investigator | **Problem ID**; **Solution Context**; **Solution Search Task + Goal**; **Main-Agent Solution Guidance** |
| Default or Senior Executor | **Implementation Context + Ownership**; **Implementation Task + Goal**; **Main-Agent Implementation Guidance** |
| Tester | **Verification Context**; **Verification Goal**; **Main-Agent Verification Guidance** |
| Archivist | **Documentation Context + Audience**; **Documentation Task + Goal**; **Main-Agent Documentation Guidance** |

Treat these parts as the complete package structure. Include only material
context, references, boundaries, decisions, constraints, intended outcomes,
approach, and cautions. Require Task ID in every report. Follow-ups repeat it
and send only changed capsule parts.

Distribute enough project knowledge and rationale for an Executor to complete
its package well. Leave bounded discovery, command selection, implementation,
deployment, self-check, and ordinary troubleshooting with that worker. Give
Senior unresolved hard-decision context when solving it is the assignment.

Give Tester acceptance intent, risks, contracts, boundaries, evidence, and any
required gates; let it design and execute the specific checks. Require every
worker to return the smallest complete decision-ready report directly to the
main and reference raw logs or bulky artifacts instead of copying them.

For one bounded context task that needs Explorer, start exactly two Explorers
in the same dispatch. Give them one shared Exploration ID and context question,
distinct Task IDs, and complementary discovery angles in each lane's
**Exploration Task + Goal**. Each lane maps the full bounded task; its angle guides evidence
collection. Keep the lanes independent. Wait for both reports and compare their
evidence and gaps before deciding. If a lane fails, retry or replace only that
lane. If replacement is unavailable, report the incomplete exploration as a
limitation.

For one bounded problem that needs Investigator, start exactly three
Investigators in the same dispatch. Give them one shared Problem ID and problem
statement, distinct Task IDs, and complementary search angles in their Solution
Search Task + Goal. Choose angles suited to the problem: different hypotheses,
solution approaches, evidence sources, or a challenge to likely assumptions.
Each lane seeks an answer to the full problem; its angle guides the search.
Keep their searches independent. Wait for all three reports and compare evidence
and disagreements rather than voting before deciding. If a lane fails, retry or
replace only that lane. If replacement is unavailable, report the incomplete
search as a limitation.

## Main-Agent Execution Boundary

For a substantive Heavy deployment, the main must not write production code or
tests, install project tooling, run deployment operations, create smoke scripts,
execute assigned verification, or perform routine operational diagnosis. Give
that work sufficient authority and context in an Executor or Tester package.
Main-owned integration and acceptance mean defining gates, assigning execution,
evaluating returned evidence, and decidingâ€”not performing the worker's checks.

The main may reason about root cause because it holds the decisive project
context. Directly inspect only the contracts, source excerpts, and failure or
verification evidence that control a material causal, architecture, scope,
risk, or acceptance decision. Use Explorer for bounded context discovery and
Investigator for evidence-backed solution search. Neither owns the main's
causal, architecture, scope, risk, or acceptance decision.

Delegate endpoint state, uploads, browser or screenshot work, external search,
routine Git/status collation, tool or API discovery, logs, environment checks,
and operational diagnostics. If a decisive check genuinely cannot be delegated,
resolve its exact operation and perform only the smallest read-only inspection
in one bounded, batched tool turn. Worker unavailability does not authorize the
main to become an Executor or Tester; reassign, replace, pause, or report the
blocker.

## Orchestration, Repair, and Lifecycle

- Dispatch independent workers that inform the same decision together. Wait for
  the relevant reports and decide once. Start another batch only when earlier
  evidence materially changes the next questions.
- Launch independent non-overlapping implementation packages together when
  dependencies allow. Preserve sequential ordering for dependencies,
  overlapping mutations, uncertainty, or risk.
- Do not poll workers, request status-only updates, inspect activity files, or
  repeatedly ask for already available evidence. Use lifecycle events and
  appropriately long waits. Use `list_agents` only to resolve genuine
  terminal-state uncertainty.
- Leave routine checks, large output, command selection, and initial failure
  diagnosis with the responsible worker. Return failed or ambiguous operational
  evidence to it instead of starting a main-agent diagnostic loop.
- When Tester finds an ordinary production defect, forward its focused evidence
  to the owning Executor for repair, then return the repair delta to the same
  Tester for recheck. Retain the main's repair and acceptance decisions. Do not
  rediagnose or repair in the main.
- Escalate to a main-owned decision only for capsule conflict, cross-package
  contract change, invalidated material assumptions, expanded ownership,
  security or migration risk, an external blocker, or repeated focused failure.
  The resulting main action is a decision and revised package, not operational
  takeover.
- After one evidence-free worker response, send one focused retry. After a
  second, replace the worker or report the limitation; do not take over its
  production or verification work.

## Fixed Boundaries

- Heavy has no workflow-imposed aggregate active-subagent limit; choose worker
  count and concurrency for the task.
- Use at most one Senior Executor and one closure reporting owner per deployment.
- Initial workers normally use `fork_turns="none"` and an explicit brief.
  Ordinary Archivist work uses `"none"`, and a new closure Archivist uses
  `"200"` under `archivist.md`.
- `fork_turns` is Codex's native spawn syntax; on OpenCode, spawn the matching
  native subagent with a fresh child session (`"none"`) or an inherited-context
  child session (`"200"`).
- Create and direct every production or verification worker yourself.
- Concurrent mutable assignments require non-overlapping ownership. Preserve
  unrelated user work and keep Git mutations within explicit authority.
- Executors own production and repair, Testers own independent verification,
  the main owns the three deployment-state documents, and Archivists receive
  only verified facts for their assigned documentation and closure reporting.
- Base every passing claim on completed, sufficiently fresh validation evidence.

## Fast Path and Closure

Use the worker-free direct fast path only when the complete request is a question
or small bounded leaf task. Do not use it for a subtask inside an already
substantive Heavy deployment.

Before the final response that completes, pauses, or blocks a substantive
deployment, update `agent_docs/project_progress.md`,
`agent_docs/project_diary.md`, and `agent_docs/latest_session_work.md` yourself,
keeping them concise and canonical. Then follow
`{{VISION_HOME}}/archivist.md` exactly once. Combine any other verified
documentation updates with its required closure assignment when practical.
Relay its handoff and exact six-column `$deployment-token-report` table. Use a
new deployment ID for each later deployment.
