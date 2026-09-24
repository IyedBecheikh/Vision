"""Composition layer for user-level and project lifecycle plans."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import RUNTIME_SCHEMA_VERSION
from .backup import append_backup_mutations, append_project_backup_mutations
from .commands import COMMAND_NAMES
from .errors import ValidationError
from .layout import USER_STATE, PackageLayout, ProjectPaths, RuntimePaths
from .plan import (
    OperationPlan,
    deduplicate,
    json_mutation,
    read_json,
    read_string_list,
    resolve_owned_runtime_path,
    text_mutation,
)
from .platform_settings import (
    MODEL_TARGETS,
    patch_orchestrator_model,
    patch_vision_settings,
    patch_worker_model,
)
from .project_ops import (
    plan_project_install,
    plan_project_remove,
    plan_project_update,
)
from .release import parse_semver
from .runtime_ops import (
    plan_runtime_files,
    plan_runtime_remove,
)
from .transaction import Mutation


def plan_bootstrap(
    package: PackageLayout,
    runtime: RuntimePaths,
    project: ProjectPaths,
    *,
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    mutations, owned_runtime, skill_cleanup = plan_runtime_files(package, runtime)
    project_plan = plan_project_install(
        package,
        project,
        legacy_local_instructions=legacy_local_instructions,
    )
    mutations.extend(project_plan.mutations)
    state = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "version": package.version,
        "owned_runtime_files": sorted(owned_runtime),
        "owned_workers": sorted(package.worker_names),
        "owned_skills": sorted(package.skill_names),
        "owned_commands": sorted(COMMAND_NAMES),
    }
    mutations.append(json_mutation(runtime.runtime / USER_STATE, state))
    return OperationPlan(
        "bootstrap",
        deduplicate(mutations),
        project_plan.warnings,
        project_plan.agent_actions,
        {"version": package.version},
        cleanup_dirs=project_plan.cleanup_dirs + skill_cleanup,
    )


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def plan_model_config(
    runtime: RuntimePaths,
    key: str,
    value: str,
) -> OperationPlan:
    """Set the workflow-owned orchestrator or Senior Executor model."""

    if value not in MODEL_TARGETS:
        raise ValidationError(
            f"unsupported model target: {value!r}; "
            f"expected one of {sorted(MODEL_TARGETS)}"
        )
    model = MODEL_TARGETS[value]
    if key == "orch":
        current = _read_optional(runtime.config_toml)
        rendered = patch_orchestrator_model(current, value)
        return OperationPlan(
            "config",
            [text_mutation(runtime.config_toml, rendered)],
            [],
            [],
            {
                "key": key,
                "value": value,
                "model": model,
                "changed": current != rendered,
            },
        )
    if key == "senior":
        worker = runtime.agents / "senior_executor.toml"
        if not worker.is_file():
            raise ValidationError(
                "the senior_executor worker is not installed; run the initial "
                "bootstrap or install before configuring it"
            )
        current = worker.read_text(encoding="utf-8")
        rendered = patch_worker_model(current, value)
        config_current = _read_optional(runtime.config_toml)
        config_rendered = patch_vision_settings(
            config_current, senior=value, senior_model=model
        )
        return OperationPlan(
            "config",
            [
                text_mutation(worker, rendered),
                text_mutation(runtime.config_toml, config_rendered),
            ],
            [],
            [],
            {
                "key": key,
                "value": value,
                "model": model,
                "changed": current != rendered
                or config_current != config_rendered,
            },
        )
    raise ValidationError(
        f"unsupported config key: {key!r}; expected 'orch' or 'senior'"
    )


def plan_remove(
    runtime: RuntimePaths,
    project: ProjectPaths,
) -> OperationPlan:
    runtime_mutations, runtime_dirs, runtime_warnings = plan_runtime_remove(runtime)
    project_mutations, project_dirs, project_warnings = plan_project_remove(project)
    return OperationPlan(
        "remove",
        deduplicate(runtime_mutations + project_mutations),
        runtime_warnings + project_warnings,
        [],
        {
            "confirmation_required": True,
            "preserves": [
                "project AGENTS.md and agent_docs/ files",
                "unrelated user AGENTS.md content",
                "unrelated Codex config.toml keys",
                "unrelated worker TOMLs",
                "unrelated skills",
            ],
        },
        cleanup_dirs=runtime_dirs + project_dirs,
    )


def plan_update(
    incoming: PackageLayout,
    runtime: RuntimePaths,
    project: ProjectPaths,
    *,
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    installed = PackageLayout.resolve(runtime.runtime, allow_legacy=True)
    project_installed = _project_installed_package(installed, runtime, project)
    project_from_version = _recorded_project_version(
        project, fallback=project_installed.version
    )
    previous_state = read_json(runtime.runtime / USER_STATE, default={})
    backup_root = (
        runtime.runtime
        / ".backups"
        / f"{installed.version}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    mutations: list[Mutation] = []
    runtime_mutations, owned_runtime, skill_cleanup = plan_runtime_files(
        incoming, runtime
    )
    append_backup_mutations(mutations, backup_root, runtime, project)
    mutations.extend(runtime_mutations)
    project_mutations, warnings = plan_project_update(
        project_installed,
        incoming,
        project,
        legacy_local_instructions=legacy_local_instructions,
    )
    mutations.extend(project_mutations)
    incoming_targets = {
        mutation.path.resolve(strict=False) for mutation in runtime_mutations
    }
    for relative in read_string_list(previous_state, "owned_runtime_files"):
        obsolete = resolve_owned_runtime_path(runtime.runtime, relative)
        if obsolete not in incoming_targets and obsolete.exists():
            mutations.append(Mutation(obsolete, None))
    # The retired legacy configuration was workflow-owned even when an older
    # ownership manifest predates its entry, so updates still remove it.
    legacy_config = runtime.runtime / "workflow_config.json"
    if (
        legacy_config.is_file()
        and legacy_config.resolve(strict=False) not in incoming_targets
    ):
        mutations.append(Mutation(legacy_config, None))
    state = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "version": incoming.version,
        "owned_runtime_files": sorted(owned_runtime),
        "owned_workers": sorted(incoming.worker_names),
        "owned_skills": sorted(incoming.skill_names),
        "owned_commands": sorted(COMMAND_NAMES),
    }
    mutations.append(json_mutation(runtime.runtime / USER_STATE, state))
    return OperationPlan(
        "update",
        deduplicate(mutations),
        warnings,
        [],
        {
            "from_version": installed.version,
            "to_version": incoming.version,
            "project_from_version": project_from_version,
            "backup": str(backup_root),
        },
        cleanup_dirs=skill_cleanup,
    )


def plan_project_only_update(
    installed: PackageLayout,
    runtime: RuntimePaths,
    project: ProjectPaths,
    *,
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    """Bring one project up to the installed user-level version."""

    project_installed = _project_installed_package(installed, runtime, project)
    project_from_version = _recorded_project_version(
        project, fallback=project_installed.version
    )
    project_mutations, warnings = plan_project_update(
        project_installed,
        installed,
        project,
        legacy_local_instructions=legacy_local_instructions,
    )
    changed = [
        mutation
        for mutation in project_mutations
        if mutation.content is None
        or not mutation.path.is_file()
        or mutation.path.read_bytes() != mutation.content
    ]
    backup_root = None
    mutations: list[Mutation] = []
    existing = [mutation for mutation in changed if mutation.path.is_file()]
    if existing:
        backup_root = (
            runtime.runtime
            / ".backups"
            / f"{project_installed.version}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        )
        append_project_backup_mutations(mutations, backup_root, project, existing)
    mutations.extend(changed)
    if warnings and not changed:
        warnings = ["current project is not workflow-installed; nothing was changed"]
    return OperationPlan(
        "project-update",
        mutations,
        warnings,
        [],
        {
            "from_version": installed.version,
            "to_version": installed.version,
            "project_from_version": project_from_version,
            "backup": str(backup_root) if backup_root else None,
        },
    )


def _project_installed_package(
    installed: PackageLayout,
    runtime: RuntimePaths,
    project: ProjectPaths,
) -> PackageLayout:
    """Resolve the package version recorded by this project's workflow state."""

    state = read_json(project.state, default={})
    legacy_entry = any(
        path.is_file()
        and "<!-- vision-id: IyedBecheikh/vision -->"
        in path.read_text(encoding="utf-8")
        for path in (project.active, project.disabled)
    )
    if not state and not legacy_entry:
        return installed
    version = state.get("workflow_version")
    if version is None:
        # Pre-state installations can only be compared with the currently
        # installed source, retaining the legacy migration behavior.
        return installed
    if not isinstance(version, str) or not version:
        raise ValidationError("project workflow_version state must be a non-empty string")
    parse_semver(version)
    if version == installed.version:
        return installed
    if not legacy_entry:
        return installed
    source_backups = (runtime.runtime / ".source_backup").resolve()
    historical_root = (source_backups / version).resolve()
    try:
        historical_root.relative_to(source_backups)
    except ValueError as error:
        raise ValidationError("project workflow_version resolves outside source backups") from error
    if not historical_root.is_dir():
        raise ValidationError(
            "the historical workflow source for this project is missing: "
            f"{historical_root}; restore it from backup before updating the project"
        )
    historical = PackageLayout.resolve(historical_root, allow_legacy=True)
    if historical.version != version:
        raise ValidationError(
            "project workflow state and historical source backup versions disagree"
        )
    return historical


def _recorded_project_version(project: ProjectPaths, *, fallback: str) -> str:
    version = read_json(project.state, default={}).get("workflow_version")
    return version if isinstance(version, str) and version else fallback
