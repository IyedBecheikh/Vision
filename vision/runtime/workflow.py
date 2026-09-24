#!/usr/bin/env python3
"""Deterministic vision lifecycle CLI.

Lifecycle commands validate and apply their mutations directly. The destructive
``remove`` command is the exception: it plans first and applies only with its
hidden confirmation flag. The hidden ``--apply`` option remains accepted for
compatibility with older launchers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    raise SystemExit("vision requires Python 3.11 or newer")

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from runtime.errors import WorkflowError
from runtime.lifecycle import (
    OperationPlan,
    PackageLayout,
    ProjectPaths,
    RuntimePaths,
)
from runtime.platform_lifecycle import (
    plan_platform_bootstrap,
    plan_platform_config,
    plan_platform_only_update,
    plan_platform_project_install,
    plan_platform_remove,
    plan_platform_update,
    resolve_platforms,
)
from runtime.platforms import PLATFORM_CHOICES, adapter_for, default_opencode_home
from runtime.platforms.opencode import opencode_is_installed, read_installed_state
from runtime.release import (
    acquire,
    parse_semver,
    select_latest,
    select_releases,
    summarize_release_notes,
)
from runtime.workers import WORKER_ROLES


def _default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _add_common(parser: argparse.ArgumentParser, *, project: bool = True) -> None:
    parser.add_argument("--codex-home", type=Path, default=_default_codex_home())
    parser.add_argument("--opencode-home", type=Path, default=default_opencode_home())
    parser.add_argument(
        "--platform",
        choices=PLATFORM_CHOICES,
        default=None,
        help="select codex, opencode, or both (default: installed clients)",
    )
    if project:
        parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", default=True, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="emit compact JSON")


def _add_local_review_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--legacy-local-instructions",
        type=Path,
        help="reviewed project-local instructions to import or replace",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install")
    _add_common(install)
    _add_local_review_option(install)
    # Retained for callers that have an extracted package available. This is
    # a read-only project-install source; install never bootstraps user files.
    install.add_argument("--package-root", type=Path, help=argparse.SUPPRESS)

    bootstrap = commands.add_parser("bootstrap", help=argparse.SUPPRESS)
    _add_common(bootstrap)
    _add_local_review_option(bootstrap)
    bootstrap.add_argument(
        "--package-root", type=Path, default=PACKAGE_ROOT
    )

    update = commands.add_parser("update")
    _add_common(update)
    # Internal hand-off from an installed launcher; not a public prompt form.
    update.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    update.add_argument("--allow-downgrade", action="store_true")
    _add_local_review_option(update)

    remove = commands.add_parser("remove")
    _add_common(remove)
    remove.add_argument("--confirm", action="store_true", help=argparse.SUPPRESS)

    config = commands.add_parser("config")
    _add_common(config, project=False)
    config.add_argument(
        "--key",
        required=True,
        choices=["orch", "senior", *sorted(WORKER_ROLES)],
    )
    config.add_argument(
        "--value",
        required=True,
        help="codex target (sol|luna) or an OpenCode provider/model#variant id",
    )

    check_update = commands.add_parser("check-update")
    _add_common(check_update, project=False)

    validate = commands.add_parser("validate")
    _add_common(validate, project=False)
    validate.add_argument("--package-root", type=Path, default=PACKAGE_ROOT)

    return parser.parse_args()


def _paths(args: argparse.Namespace) -> tuple[RuntimePaths, ProjectPaths | None]:
    runtime = RuntimePaths(args.codex_home.expanduser().resolve())
    project = ProjectPaths(args.project.resolve()) if hasattr(args, "project") else None
    return runtime, project


def _platforms(args: argparse.Namespace, *, prompt: bool | None = None) -> list[str]:
    if prompt is None:
        prompt = not getattr(args, "json", False)
    return resolve_platforms(
        getattr(args, "platform", None),
        codex_home=args.codex_home.expanduser().resolve(),
        opencode_home=args.opencode_home.expanduser().resolve(),
        prompt=prompt,
    )


def _emit(value: dict[str, object], *, compact: bool) -> None:
    if compact:
        print(json.dumps(value, separators=(",", ":"), sort_keys=True))
    else:
        print(json.dumps(value, indent=2, sort_keys=True))


def _finish(plan: OperationPlan, args: argparse.Namespace) -> int:
    summary = plan.summary()
    summary["applied"] = True
    plan.apply()
    _emit(summary, compact=args.json)
    return 0


def _package_root(path: Path) -> Path:
    """Resolve a package path without applying a version-specific schema."""

    root = path.expanduser().resolve()
    if not _has_package_version(root):
        nested = root / "vision"
        if _has_package_version(nested):
            root = nested
    return root


def _has_package_version(root: Path) -> bool:
    return (root / "operate" / "VERSION").is_file() or (root / "VERSION").is_file()


def _version_path(root: Path) -> Path:
    current = root / "operate" / "VERSION"
    return current if current.is_file() else root / "VERSION"


def _opencode_adapter(args: argparse.Namespace):
    return adapter_for(
        "opencode", opencode_home=args.opencode_home.expanduser().resolve()
    )


def _installed_version(args: argparse.Namespace) -> str | None:
    runtime = RuntimePaths(args.codex_home.expanduser().resolve())
    if _has_package_version(runtime.runtime):
        return _version_path(runtime.runtime).read_text(encoding="utf-8").strip()
    adapter = _opencode_adapter(args)
    if opencode_is_installed(adapter):
        version = read_installed_state(adapter).get("version")
        if isinstance(version, str) and version:
            return version
    return None


def _installed_source_root(args: argparse.Namespace) -> Path:
    runtime = RuntimePaths(args.codex_home.expanduser().resolve())
    if _has_package_version(runtime.runtime):
        return runtime.runtime
    adapter = _opencode_adapter(args)
    if opencode_is_installed(adapter):
        return adapter.runtime_paths().workflow_home
    raise WorkflowError("no installed platform was found; run the bootstrap first")


def _package_version(root: Path) -> object:
    """Read the minimal update-ordering metadata without applying a package schema."""

    version_path = _version_path(root)
    try:
        lines = version_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise WorkflowError(f"cannot read incoming package VERSION: {error}") from error
    if len(lines) != 1 or not lines[0]:
        raise WorkflowError("incoming package VERSION must contain exactly one non-empty line")
    try:
        return parse_semver(lines[0])
    except Exception as error:
        raise WorkflowError(f"incoming package VERSION is invalid: {lines[0]!r}") from error


def _delegate_update(incoming_root: Path, args: argparse.Namespace) -> int:
    current = incoming_root / "runtime" / "workflow.py"
    workflow = current if current.is_file() else incoming_root / "workflow.py"
    if not workflow.is_file():
        raise WorkflowError(f"incoming package workflow entry point is missing: {incoming_root}")
    command = [
        sys.executable,
        "-B",
        str(workflow),
        "update",
        "--source",
        str(incoming_root),
        "--codex-home",
        str(args.codex_home),
        "--opencode-home",
        str(args.opencode_home),
        "--project",
        str(args.project),
    ]
    if getattr(args, "platform", None):
        command.extend(["--platform", args.platform])
    if args.allow_downgrade:
        command.append("--allow-downgrade")
    if args.legacy_local_instructions:
        command.extend(
            ["--legacy-local-instructions", str(args.legacy_local_instructions)]
        )
    if args.apply:
        command.append("--apply")
    if args.json:
        command.append("--json")
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    args = parse_args()
    temporary = None
    try:
        runtime, project = _paths(args)
        if args.command == "validate":
            package = PackageLayout.resolve(args.package_root)
            _emit(
                {
                    "valid": True,
                    "version": package.version,
                    "workers": sorted(package.worker_names),
                    "skills": sorted(package.skill_names),
                },
                compact=args.json,
            )
            return 0
        if args.command == "check-update":
            installed_text = _installed_version(args)
            if installed_text is None:
                raise WorkflowError(
                    "no installed platform was found; complete the bootstrap first"
                )
            installed = parse_semver(installed_text)
            releases = select_releases()
            newer = [release for release in releases if release.version > installed]
            latest = releases[0]
            updates = [
                {
                    "version": release.version_text,
                    "asset": release.zip_name,
                    "release_url": release.release_url,
                    "release_notes": release.release_notes,
                    "summary": summarize_release_notes(release.release_notes),
                }
                for release in newer
            ]
            if newer:
                status = "update available"
                summary = "\n".join(
                    f"{item['version']}: {item['summary']}" for item in updates
                )
            elif latest.version == installed:
                status = "current"
                summary = "The installed workflow is current."
            else:
                status = "installed newer"
                summary = "The installed workflow is newer than the latest release."
            _emit(
                {
                    "status": status,
                    "installed": installed_text,
                    "available": latest.version_text,
                    "asset": latest.zip_name,
                    "summary": summary,
                    "updates": updates,
                },
                compact=args.json,
            )
            return 0
        if args.command == "remove":
            assert project is not None
            platforms = _platforms(args)
            plan = plan_platform_remove(
                codex_home=args.codex_home.expanduser().resolve(),
                opencode_home=args.opencode_home.expanduser().resolve(),
                platforms=platforms,
                project=project,
            )
            if not args.confirm:
                summary = plan.summary()
                summary["applied"] = False
                summary["confirmation_required"] = True
                _emit(summary, compact=args.json)
                return 0
            return _finish(plan, args)
        if args.command == "config":
            platforms = _platforms(args, prompt=False)
            return _finish(
                plan_platform_config(
                    key=args.key,
                    value=args.value,
                    codex_home=args.codex_home.expanduser().resolve(),
                    opencode_home=args.opencode_home.expanduser().resolve(),
                    platforms=platforms,
                ),
                args,
            )
        if args.command == "bootstrap":
            assert project is not None
            package = PackageLayout.resolve(args.package_root)
            legacy_local = (
                args.legacy_local_instructions.read_text(encoding="utf-8")
                if args.legacy_local_instructions
                else None
            )
            platforms = _platforms(args)
            return _finish(
                plan_platform_bootstrap(
                    package,
                    codex_home=args.codex_home.expanduser().resolve(),
                    opencode_home=args.opencode_home.expanduser().resolve(),
                    platforms=platforms,
                    project=project,
                    legacy_local_instructions=legacy_local,
                ),
                args,
            )
        if args.command == "install":
            assert project is not None
            legacy_local = (
                args.legacy_local_instructions.read_text(encoding="utf-8")
                if args.legacy_local_instructions
                else None
            )
            if project.active.exists() and project.disabled.exists():
                raise WorkflowError("both active and disabled project entry points exist")
            platforms = _platforms(args)
            adapter = _opencode_adapter(args)
            if _has_package_version(runtime.runtime):
                package = PackageLayout.resolve(runtime.runtime)
            elif opencode_is_installed(adapter):
                package = PackageLayout.resolve(adapter.runtime_paths().workflow_home)
            elif args.package_root is not None:
                package = PackageLayout.resolve(args.package_root)
            else:
                raise WorkflowError(
                    "the user-level workflow bootstrap is not installed; "
                    "complete the initial bootstrap before installing a project"
                )
            plan = plan_platform_project_install(
                package,
                platforms=platforms,
                project=project,
                legacy_local_instructions=legacy_local,
            )
            documentation_action_required = any(
                action.get("files") for action in plan.agent_actions
            )
            if plan.mutations or plan.cleanup_dirs or documentation_action_required:
                return _finish(plan, args)
            summary = plan.summary()
            summary["applied"] = False
            summary["status"] = "already installed"
            _emit(summary, compact=args.json)
            return 0
        if args.command == "update":
            assert project is not None
            platforms = _platforms(args)
            installed_text = _installed_version(args)
            if installed_text is None:
                raise WorkflowError(
                    "no installed platform was found; complete the bootstrap first"
                )
            installed = parse_semver(installed_text)
            if args.source:
                incoming_root = _package_root(args.source)
            else:
                selected = select_latest()
                if selected.version == installed:
                    # The installed source is already verified and is the
                    # template authority for projects that lag behind it.
                    incoming_root = _installed_source_root(args)
                else:
                    temporary, package_path = acquire(selected)
                    incoming_root = _package_root(package_path)
            incoming_semver = _package_version(incoming_root)
            if incoming_semver < installed and not args.allow_downgrade:
                raise WorkflowError(
                    "incoming version is older; pass --allow-downgrade after approval"
                )
            if incoming_semver == installed:
                legacy_local = (
                    args.legacy_local_instructions.read_text(encoding="utf-8")
                    if args.legacy_local_instructions
                    else None
                )
                plan = plan_platform_only_update(
                    codex_home=args.codex_home.expanduser().resolve(),
                    opencode_home=args.opencode_home.expanduser().resolve(),
                    platforms=platforms,
                    project=project,
                    legacy_local_instructions=legacy_local,
                )
                if not plan.mutations:
                    summary = plan.summary()
                    summary["applied"] = False
                    summary["status"] = (
                        "project not installed"
                        if plan.warnings
                        else "already current"
                    )
                    _emit(summary, compact=args.json)
                    return 0
                return _finish(plan, args)
            if incoming_root != PACKAGE_ROOT:
                # The incoming runtime owns package validation. An installed
                # launcher may be older than the package it is updating to and
                # must not reject files removed by that newer package.
                return _delegate_update(incoming_root, args)
            incoming = PackageLayout.resolve(incoming_root)
            legacy_local = (
                args.legacy_local_instructions.read_text(encoding="utf-8")
                if args.legacy_local_instructions
                else None
            )
            return _finish(
                plan_platform_update(
                    incoming,
                    codex_home=args.codex_home.expanduser().resolve(),
                    opencode_home=args.opencode_home.expanduser().resolve(),
                    platforms=platforms,
                    project=project,
                    legacy_local_instructions=legacy_local,
                ),
                args,
            )
        raise WorkflowError(f"unsupported command: {args.command}")
    except (OSError, WorkflowError) as error:
        _emit({"error": str(error), "applied": False}, compact=getattr(args, "json", False))
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
