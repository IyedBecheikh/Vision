# vision 1.1.15 — Experimental release notes

## Overview

Version 1.1.15 tightens the Medium and Heavy orchestration contracts around
project-context intake, worker eligibility, and production ownership. The goal
is to reduce repeated main-agent context loading while preserving its authority
over architecture, root cause, integration, acceptance, and final claims.

## Shared deployment intake

- The first Medium or Heavy deployment-state entry now initializes exactly one
  persistent Companion before planning, mutations, or other worker dispatch.
- Companion receives a substantial initial context assignment, retains useful
  diary and module detail, and is reused across route changes.
- The main still reads the complete `agent_docs/` framework exactly once per
  session. Later large syntheses, delta checks, and conflict checks belong to
  Companion when they are useful.
- Companion assignments should be consolidated because every rollout reloads
  its retained context. Status-only calls, repeated broad summaries, and tiny
  lookups already answerable from current context are discouraged.

## Context routing and investigation

After intake, Medium and Heavy create a compact working-context map:

- `Direct` covers decision-critical material the main must understand.
- `Companion` covers supporting modules, tools, configuration, logs,
  dependencies, and other bulky project context.
- `Investigator` covers one unfamiliar or ambiguous evidence gap that benefits
  from independent project inspection, Internet research, or both.

Investigator is no longer limited to Internet-only questions. It remains
read-only and supplies evidence and implications; the main retains every
root-cause, architecture, implementation, and acceptance decision.

## Heavy execution boundary

- Heavy keeps the main as the central knowledge director and prohibits it from
  becoming a production Executor, deployment operator, repair worker, or
  independent Tester during substantive deployments.
- Executors own their bounded implementation, operational checks, and ordinary
  repair. Tester owns independent verification and its assigned test assets.
- Failed routine operational evidence returns to the responsible worker. The
  main evaluates evidence and revises decisions or packages instead of entering
  a repeated diagnostic loop.
- Main-owned reads and worker dispatches are batched when independent. Polling,
  status-only requests, and duplicated routine checks are explicitly avoided.

Medium preserves its separate ownership model: planning, root-cause reasoning,
implementation, repair, and verification remain with the main agent.

## Documentation and validation

- Archivist guidance now requires concise canonical documents, removal of stale
  or redundant detail, and recoverable deployment handoffs.
- Runtime contract tests cover the shared intake lifecycle, context map,
  Investigator scope, Heavy ownership boundaries, rollout guidance, and concise
  documentation requirements.

## Artifact

- Artifact: `dist/vision-1.1.15.zip`.
- SHA-256: `6ff393d8747fde32ece10d7dbe2a9fee4783b76f9b6ca6d9ae248b2c47d37431`.
- The archive passed package verification, the 58-test runtime suite, and the
  8-test Deployment Token Report suite.
- The release workflow rebuilds and validates the package from tag `v1.1.15`
  before publishing it as a prerelease.
