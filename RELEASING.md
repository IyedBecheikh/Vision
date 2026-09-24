# Release Process

This repository publishes the workflow as GitHub Release assets. The release
payload is intentionally independent of the repository presentation and
development files.

## Repository and asset layout

The repository-only release machinery is:

```text
.github/workflows/release.yml
scripts/package_release.py
RELEASING.md
```

Every archive contains exactly this top-level directory and nothing beside it:

```text
vision/
â”œâ”€â”€ operate/
â”‚   â”œâ”€â”€ VERSION
â”‚   â”œâ”€â”€ user_AGENTS.md                  # merged workflow policy + commands
â”‚   â””â”€â”€ lifecycle guides
â”œâ”€â”€ runtime/
â”‚   â”œâ”€â”€ workflow.py
â”œâ”€â”€ agents/
â””â”€â”€ project_docs/
```

The package does not contain `README.md`, `illustration.png`,
`workflow_breakdown.md`, `RELEASING.md`, `.github/`, `scripts/`, `.git/`, or any
other repository-only file. All files below `vision/` are included so
the installed workflow remains self-contained.

Each GitHub Release publishes one universal asset for every supported operating
system:

- `vision-<version>.zip`;
- `SHA256SUMS` for the ZIP asset.

## Versioning

Use SemVer 2.0.0. Keep the plain version in
`vision/operate/VERSION` and the `vision-version` marker in
`vision/operate/user_AGENTS.md` identical.
The release tag is the same value with an optional leading `v`, for example
`VERSION=1.0.0` and tag `v1.0.0`. GitHub's prerelease flag is independent of
the SemVer string; tag pushes for `v1` and later stable releases are published
as normal releases, while manual dispatch defaults to a prerelease unless
disabled.
The command examples below use the current package version, `1.0.0`; replace
that value consistently when preparing a later release.

## Local build and validation

Run these commands from the repository root. The builder uses only Python's
standard library, requires Python 3.11 or newer, and works on Linux, macOS, and
Windows.

Linux/macOS:

```sh
python3 -B scripts/test_workflow_runtime.py -v
python3 -B scripts/test_deployment_token_report.py -v
python3 scripts/package_release.py --release-tag v1.0.0 --output-dir dist
python3 scripts/package_release.py --verify dist/vision-1.0.0.zip --version 1.0.0
```

Windows PowerShell:

```powershell
py -3.11 -B scripts\test_workflow_runtime.py -v
py -3.11 -B scripts\test_deployment_token_report.py -v
py -3.11 scripts/package_release.py --release-tag v1.0.0 --output-dir dist
py -3.11 scripts/package_release.py --verify dist\vision-1.0.0.zip --version 1.0.0
```

The build validates the version, marker, lifecycle runtime, and required
resources; rejects generated Python caches; creates a deterministic ZIP asset;
and writes `dist/SHA256SUMS`. Run the runtime tests before packaging and inspect
the archive listing when package contents change.

## Publishing â€” approval required

Do not run the following commands until the release structure, contents, tag,
and prerelease setting have been approved:

```sh
git status --short
git tag -a v1.0.0 -m "vision v1.0.0"
git push origin v1.0.0
```

Pushing a semantic `v*` tag starts `.github/workflows/release.yml`. It rebuilds
and validates the archives from that tagged commit, then publishes the GitHub
Release with generated notes. Tag pushes for stable releases (the `v1` line and
later) publish normal releases; the workflow also supports a manual dispatch
with a tag, which checks out that tag before packaging and defaults to a
prerelease unless the `prerelease` input is set to false.

If the workflow is unavailable, the equivalent manual publication command is:

```sh
gh release create v1.0.0 \
  dist/vision-1.0.0.zip \
  dist/SHA256SUMS \
  --title "vision v1.0.0" \
  --generate-notes
```

The manual command is also approval-gated and must use assets built from the
same tagged commit.

## Consumer commands

- Initial installation reads the extracted release package's
  `vision/operate/bootstrap.md`; the bundled lifecycle CLI validates and
  applies the user-level bootstrap transaction directly.
- `vision --install` reads the installed `operate/install.md` and creates only
  project-level workflow assets from the existing bootstrap.
- `vision --check-update` explicitly checks GitHub Releases without
  downloading or installing an update.
- `vision --update` selects the latest appropriate ZIP asset, downloads
  it from its GitHub Release URL, verifies it, and follows the package's update
  procedure. It never clones the repository.
- `vision --remove` first displays a destructive dry-run summary and
  requires one explicit second confirmation before deleting workflow-owned
  files.
