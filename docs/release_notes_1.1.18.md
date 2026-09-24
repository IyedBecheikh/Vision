# vision 1.1.18 — Specialized discovery and reliable multi-project updates

Version 1.1.18 expands project-aware investigation, separates context discovery
from solution research, improves parallel investigation and worker waiting, and
fixes sequential project updates. It also removes the experimental Companion
report intermediary.

## Investigator and Explorer roles

- Investigator can use both project evidence and Internet sources to research
  fault hypotheses, possible solutions, technical alternatives, feasibility,
  tradeoffs, and prior art. It is no longer framed as Internet-only solution
  searching.
- Explorer is a separate read-only role for bounded project-context discovery,
  source and contract mapping, document intake, and evidence retrieval.
- This split keeps existing-project exploration with Explorer and solution
  search with Investigator while the main agent retains interpretation and all
  project decisions.

## Parallel investigation and worker waiting

- A single bounded Investigator problem now uses exactly three independent
  Investigator lanes with a shared Problem ID, distinct Task IDs, and
  complementary search angles. The main compares all three reports rather than
  voting.
- Installation and full user-level update now generate
  `[features.multi_agent_v2]` settings with a 120-second minimum wait, a
  300-second default wait, and a 1,800-second maximum wait. Removal deletes
  these workflow-owned settings.

## Reliable updates across multiple projects

Updating the user-level workflow through one project no longer prevents later
projects from updating from their older workflow version. The runtime retains
and resolves the historical package source for each project's recorded version,
so subsequent project-only updates can migrate safely and create scoped backups.

## Companion removal

Companion has been completely removed from the active role set, route
instructions, package validation, and generated installations. Testing showed
that it was ineffective as a report intermediary, and custom workers could not
reliably use peer-to-peer communication. Workers now return compact,
evidence-linked reports directly to the main agent through the parent-child
result channel; the existing batching guidelines remain in force.

Upgrading from 1.1.17 removes the workflow-owned Companion definition and
template while preserving unrelated custom workers.

## Validation and artifact

- Artifact: `vision-1.1.18.zip`.
- SHA-256: `bc7dbf6d96c1b8096175366c5a9bfb3a5b9508d9b864518a531cc2b52d42575c`.
- Validation passed: 60 runtime tests, 9 Deployment Token Report tests,
  package-schema validation, archive-content inspection, and independent archive
  verification.
