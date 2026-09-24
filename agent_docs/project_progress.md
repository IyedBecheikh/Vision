# Project Progress

## Goal

Add native OpenCode support to Vision as a second runtime backend without
changing or duplicating the existing Codex workflow, and expose Vision's common
workflow actions through each client's native command UX.

## Overall Progress

Complete. Platform abstraction, canonical worker store, OpenCode install /
update / remove / config, platform selection, dual token-report backends, and
native command surfaces (Codex skills and OpenCode slash commands) are
implemented and covered by tests.

## Current Position

All 91 runtime and token-report tests pass; package validation and the release
build succeed. Codex behavior is unchanged.

## Next Milestone

Release a version that ships the OpenCode backend and native commands, then
verify an end-to-end OpenCode Heavy-route deployment using native
child/subagent sessions.
