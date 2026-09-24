# vision 1.2.0

## Unified instruction ownership

- Shared workflow principles, route selection, documentation intake, rollout
  policy, and lifecycle dispatch now occupy one managed region in user-level
  `~/.codex/AGENTS.md`.
- Project `AGENTS.md` is native project-owned personalization. New installs do
  not create, wrap, move, ignore, or modify it.
- Update and removal safely unwrap recognized legacy project entries into
  ordinary project instructions. The custom personalization, enable, and
  disable commands and their resources are retired.

## Two-lane Explorer batches

- Each bounded Explorer task now starts exactly two independent Explorer lanes
  in one dispatch, with one shared Exploration ID, distinct Task IDs, and
  complementary discovery angles.
- The main compares both evidence-linked reports before deciding and retries or
  replaces only a failed lane.

## Platform wait setting

- The generated minimum multi-agent wait timeout is now 300000 ms. The default
  remains 300000 ms and the maximum remains 1800000 ms.
