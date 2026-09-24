# Project Core Technologies

## Languages and Runtimes

- Python 3.11 or newer (standard library only for the lifecycle runtime).

## Frameworks and Libraries

- No third-party runtime dependencies; `tomllib`, `zipfile`, `urllib`,
  `argparse`, and `unittest` from the standard library.

## Build, Test, and Development Tools

- `scripts/package_release.py` builds and verifies the release ZIP and
  `SHA256SUMS`.
- `scripts/test_workflow_runtime.py` and
  `scripts/test_deployment_token_report.py` are `unittest` suites.
- GitHub Actions (`.github/workflows/release.yml`) builds and publishes releases.

## External Services and Infrastructure

- GitHub Releases API for `--check-update` and `--update` (repository
  `IyedBecheikh/vision`).
- Codex CLI/app local configuration under `~/.codex/` (or `CODEX_HOME`).
- OpenCode local configuration under `~/.config/opencode/` (or
  `OPENCODE_HOME`/`XDG_CONFIG_HOME`); provider auth, credentials, and the
  main-session model stay OpenCode-owned.

## Important Technical Constraints

- The runtime is transactional and refuses symlinks, duplicate archive members,
  checksum mismatches, and unowned file collisions.
- Ownership markers and IDs (`vision-*`) gate removal and migration safety.
- One canonical worker instruction body per role is rendered per platform; a
  worker sync tool and package validation keep the Codex TOML rendering from
  drifting from the canonical store.
- Platform selection (`codex`, `opencode`, `both`) is persisted in each
  installation's `install_state.json`; ownership is never inferred from `$PATH`.
- The deployment token report has a Codex backend and an OpenCode backend behind
  one shared entry point, with an identical six-column output.
