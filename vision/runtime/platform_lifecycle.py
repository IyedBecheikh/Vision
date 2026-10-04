"""Platform-aware composition of Vision lifecycle plans.

Codex keeps its established plan functions unchanged. This module adds the
OpenCode equivalents and merges both when the ``both`` platform is selected so
one workflow drives either or both native clients.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import RUNTIME_SCHEMA_VERSION
from .commands import COMMAND_NAMES
from .errors import ValidationError
from .layout import USER_STATE, PackageLayout, ProjectPaths, RuntimePaths
from .lifecycle import (
    plan_model_config,
    plan_project_install,
    plan_project_remove,
    plan_project_update,
    plan_remove,
    plan_update,
)
from .plan import (
    OperationPlan,
    deduplicate,
    json_mutation,
    read_json,
    read_string_list,
    resolve_owned_runtime_path,
)
from .platform_settings import CLAUDE_MODEL_TARGETS, MODEL_TARGETS
from .platforms import adapter_for, expand_selection
from .platforms.base import PlatformAdapter
from .platforms.claude import (
    ClaudeAdapter,
    claude_is_installed,
    parse_claude_model,
    plan_claude_runtime,
)
from .platforms.opencode import (
    OpenCodeAdapter,
    opencode_is_installed,
    plan_opencode_runtime,
)
from .workers import WORKER_ROLES, load_worker_specs
from .transaction import Mutation


def _codex_runtime_paths(codex_home: Path) -> RuntimePaths:
    return RuntimePaths(codex_home.expanduser().resolve())


def codex_is_installed(codex_home: Path) -> bool:
    return (codex_home / "vision" / "operate" / "VERSION").is_file()


def _claude_adapter(claude_home: Path | None) -> ClaudeAdapter:
    adapter = adapter_for("claude", claude_home=claude_home)
    assert isinstance(adapter, ClaudeAdapter)
    return adapter


def installed_platforms(
    *,
    codex_home: Path,
    opencode_home: Path,
    claude_home: Path | None = None,
) -> list[str]:
    installed: list[str] = []
    if codex_is_installed(codex_home):
        installed.append("codex")
    if opencode_is_installed(adapter_for("opencode", opencode_home=opencode_home)):
        installed.append("opencode")
    if claude_is_installed(adapter_for("claude", claude_home=claude_home)):
        installed.append("claude")
    return installed


def _codex_state(
    package: PackageLayout, platforms: list[str], owned_runtime: set[str]
) -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "version": package.version,
        "platform": "codex",
        "platforms": sorted(set(platforms)),
        "owned_runtime_files": sorted(owned_runtime),
        "owned_workers": sorted(package.worker_names),
        "owned_skills": sorted(package.skill_names),
        "owned_commands": sorted(COMMAND_NAMES),
    }


def plan_platform_bootstrap(
    package: PackageLayout,
    *,
    codex_home: Path,
    opencode_home: Path,
    platforms: list[str],
    project: ProjectPaths,
    legacy_local_instructions: str | None = None,
    claude_home: Path | None = None,
) -> OperationPlan:
    mutations: list[Mutation] = []
    warnings: list[str] = []
    cleanup: list[Path] = []
    project_plan = plan_project_install(
        package,
        project,
        legacy_local_instructions=legacy_local_instructions,
    )
    mutations.extend(project_plan.mutations)
    warnings.extend(project_plan.warnings)
    cleanup.extend(project_plan.cleanup_dirs)

    if "codex" in platforms:
        from .runtime_ops import plan_runtime_files

        runtime = _codex_runtime_paths(codex_home)
        codex_mutations, owned_runtime, skill_cleanup = plan_runtime_files(package, runtime)
        mutations.extend(codex_mutations)
        cleanup.extend(skill_cleanup)
        mutations.append(
            json_mutation(
                runtime.runtime / USER_STATE,
                _codex_state(package, platforms, owned_runtime),
            )
        )
    if "opencode" in platforms:
        adapter = adapter_for("opencode", opencode_home=opencode_home)
        opencode_mutations, _, skill_cleanup = plan_opencode_runtime(
            package, adapter, platforms=platforms
        )
        mutations.extend(opencode_mutations)
        cleanup.extend(skill_cleanup)
    if "claude" in platforms:
        adapter = _claude_adapter(claude_home)
        claude_mutations, _, skill_cleanup = plan_claude_runtime(
            package, adapter, platforms=platforms
        )
        mutations.extend(claude_mutations)
        cleanup.extend(skill_cleanup)

    return OperationPlan(
        "bootstrap",
        deduplicate(mutations),
        warnings,
        project_plan.agent_actions,
        {"version": package.version, "platforms": sorted(set(platforms))},
        cleanup_dirs=cleanup,
    )


def plan_platform_project_install(
    package: PackageLayout,
    *,
    platforms: list[str],
    project: ProjectPaths,
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    del platforms  # project resources are platform-neutral
    return plan_project_install(
        package,
        project,
        legacy_local_instructions=legacy_local_instructions,
    )


def _append_adapter_backup(
    mutations: list[Mutation],
    backup_root: Path,
    adapter: PlatformAdapter,
    project: ProjectPaths,
    state: dict[str, Any],
) -> None:
    paths = adapter.runtime_paths()
    targets: list[Path] = []
    for path in (paths.instructions_file,):
        if path.is_file():
            targets.append(path)
    if paths.workflow_home.is_dir():
        targets.extend(
            path
            for path in paths.workflow_home.rglob("*")
            if path.is_file()
            and ".backups" not in path.parts
            and ".source_backup" not in path.parts
        )
    for role in read_string_list(state, "owned_workers"):
        candidate = paths.agents_dir / f"{role}.md"
        if candidate.is_file():
            targets.append(candidate)
    for skill in read_string_list(state, "owned_skills"):
        skill_root = paths.skills_dir / skill
        if skill_root.is_dir():
            targets.extend(path for path in skill_root.rglob("*") if path.is_file())
    targets.extend(
        path
        for path in (project.active, project.disabled, project.personalization, project.state, project.gitignore)
        if path.is_file()
    )
    seen: set[Path] = set()
    for source in targets:
        resolved = source.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            relative = Path("user") / source.relative_to(paths.client_home)
        except ValueError:
            relative = Path("project") / source.relative_to(project.root)
        mutations.append(Mutation(backup_root / relative, source.read_bytes()))


def _plan_adapter_update(
    incoming: PackageLayout,
    adapter: PlatformAdapter,
    project: ProjectPaths,
    *,
    platforms: list[str],
    plan_runtime: Any,
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    label = adapter.platform.capitalize()
    state = read_json(adapter.runtime_paths().state_file, default={})
    if not state:
        raise ValidationError(
            f"{label} Vision is not installed; run the initial bootstrap first"
        )
    installed_version = str(state.get("version", "unknown"))
    backup_root = (
        adapter.runtime_paths().workflow_home
        / ".backups"
        / f"{installed_version}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    mutations: list[Mutation] = []
    _append_adapter_backup(mutations, backup_root, adapter, project, state)
    runtime_mutations, _, skill_cleanup = plan_runtime(
        incoming, adapter, platforms=platforms, previous_state=state
    )
    mutations.extend(runtime_mutations)
    incoming_targets = {mutation.path.resolve(strict=False) for mutation in runtime_mutations}
    for relative in read_string_list(state, "owned_runtime_files"):
        obsolete = resolve_owned_runtime_path(adapter.runtime_paths().workflow_home, relative)
        if obsolete not in incoming_targets and obsolete.exists():
            mutations.append(Mutation(obsolete, None))
    project_mutations, warnings = plan_project_update(
        incoming,
        incoming,
        project,
        legacy_local_instructions=legacy_local_instructions,
    )
    mutations.extend(project_mutations)
    return OperationPlan(
        "update",
        deduplicate(mutations),
        warnings,
        [],
        {
            "from_version": installed_version,
            "to_version": incoming.version,
            "backup": str(backup_root),
        },
        cleanup_dirs=skill_cleanup,
    )


def plan_opencode_update(
    incoming: PackageLayout,
    adapter: OpenCodeAdapter,
    project: ProjectPaths,
    *,
    platforms: list[str],
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    return _plan_adapter_update(
        incoming,
        adapter,
        project,
        platforms=platforms,
        plan_runtime=plan_opencode_runtime,
        legacy_local_instructions=legacy_local_instructions,
    )


def plan_claude_update(
    incoming: PackageLayout,
    adapter: ClaudeAdapter,
    project: ProjectPaths,
    *,
    platforms: list[str],
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    return _plan_adapter_update(
        incoming,
        adapter,
        project,
        platforms=platforms,
        plan_runtime=plan_claude_runtime,
        legacy_local_instructions=legacy_local_instructions,
    )


def _merge(operation: str, plans: list[OperationPlan]) -> OperationPlan:
    mutations: list[Mutation] = []
    warnings: list[str] = []
    actions: list[dict[str, Any]] = []
    cleanup: list[Path] = []
    details: dict[str, Any] = {}
    for plan in plans:
        mutations.extend(plan.mutations)
        warnings.extend(plan.warnings)
        actions.extend(plan.agent_actions)
        cleanup.extend(plan.cleanup_dirs)
        details.update(plan.details)
    return OperationPlan(
        operation,
        deduplicate(mutations),
        warnings,
        actions,
        details,
        cleanup_dirs=cleanup,
    )


def plan_platform_update(
    incoming: PackageLayout,
    *,
    codex_home: Path,
    opencode_home: Path,
    platforms: list[str],
    project: ProjectPaths,
    legacy_local_instructions: str | None = None,
    claude_home: Path | None = None,
) -> OperationPlan:
    plans: list[OperationPlan] = []
    if "codex" in platforms:
        if not codex_is_installed(codex_home):
            raise ValidationError("Codex Vision is not installed; complete the Codex bootstrap first")
        plans.append(
            plan_update(
                incoming,
                _codex_runtime_paths(codex_home),
                project,
                legacy_local_instructions=legacy_local_instructions,
            )
        )
    if "opencode" in platforms:
        adapter = adapter_for("opencode", opencode_home=opencode_home)
        if not opencode_is_installed(adapter):
            raise ValidationError(
                "OpenCode Vision is not installed; complete the OpenCode bootstrap first"
            )
        plans.append(
            plan_opencode_update(
                incoming,
                adapter,
                project,
                platforms=platforms,
                legacy_local_instructions=legacy_local_instructions,
            )
        )
    if "claude" in platforms:
        adapter = _claude_adapter(claude_home)
        if not claude_is_installed(adapter):
            raise ValidationError(
                "Claude Code Vision is not installed; complete the Claude Code bootstrap first"
            )
        plans.append(
            plan_claude_update(
                incoming,
                adapter,
                project,
                platforms=platforms,
                legacy_local_instructions=legacy_local_instructions,
            )
        )
    return _merge("update", plans)


def _plan_adapter_remove(
    adapter: PlatformAdapter,
    project: ProjectPaths,
    *,
    preserves: list[str],
) -> OperationPlan | None:
    if not (adapter.runtime_paths().workflow_home / "operate" / "VERSION").is_file():
        return None
    state = read_json(adapter.runtime_paths().state_file, default={})
    mutations, cleanup, warnings = adapter.remove_owned_resources(state)
    project_mutations, project_dirs, project_warnings = plan_project_remove(project)
    mutations = list(mutations) + list(project_mutations)
    cleanup = list(cleanup) + list(project_dirs)
    warnings = list(warnings) + list(project_warnings)
    return OperationPlan(
        "remove",
        deduplicate(mutations),
        warnings,
        [],
        {"confirmation_required": True, "preserves": preserves},
        cleanup_dirs=cleanup,
    )


def plan_platform_remove(
    *,
    codex_home: Path,
    opencode_home: Path,
    platforms: list[str],
    project: ProjectPaths,
    claude_home: Path | None = None,
) -> OperationPlan:
    plans: list[OperationPlan] = []
    if "codex" in platforms:
        plans.append(plan_remove(_codex_runtime_paths(codex_home), project))
    if "opencode" in platforms:
        adapter = adapter_for("opencode", opencode_home=opencode_home)
        plan = _plan_adapter_remove(
            adapter,
            project,
            preserves=[
                "project AGENTS.md and agent_docs/ files",
                "unrelated user AGENTS.md content",
                "OpenCode opencode.json and provider settings",
                "unrelated OpenCode agents",
                "unrelated OpenCode skills",
            ],
        )
        if plan is not None:
            plans.append(plan)
    if "claude" in platforms:
        adapter = _claude_adapter(claude_home)
        plan = _plan_adapter_remove(
            adapter,
            project,
            preserves=[
                "project AGENTS.md and agent_docs/ files",
                "unrelated user CLAUDE.md content",
                "Claude Code settings.json and provider settings",
                "unrelated Claude Code agents",
                "unrelated Claude Code skills",
            ],
        )
        if plan is not None:
            plans.append(plan)
    if not plans:
        raise ValidationError("no installed platform matches the removal selection")
    return _merge("remove", plans)


def plan_platform_only_update(
    *,
    codex_home: Path,
    opencode_home: Path,
    platforms: list[str],
    project: ProjectPaths,
    legacy_local_instructions: str | None = None,
    claude_home: Path | None = None,
) -> OperationPlan:
    """Bring one project up to the installed user-level version for each platform."""

    from .lifecycle import plan_project_only_update

    plans: list[OperationPlan] = []
    if "codex" in platforms:
        codex_runtime = _codex_runtime_paths(codex_home)
        plans.append(
            plan_project_only_update(
                PackageLayout.resolve(codex_runtime.runtime, allow_legacy=True),
                codex_runtime,
                project,
                legacy_local_instructions=legacy_local_instructions,
            )
        )
    if "opencode" in platforms:
        adapter = adapter_for("opencode", opencode_home=opencode_home)
        workflow_home = adapter.runtime_paths().workflow_home
        plans.append(
            plan_project_only_update(
                PackageLayout.resolve(workflow_home),
                RuntimePaths(workflow_home),
                project,
                legacy_local_instructions=legacy_local_instructions,
            )
        )
    if "claude" in platforms:
        adapter = _claude_adapter(claude_home)
        workflow_home = adapter.runtime_paths().workflow_home
        plans.append(
            plan_project_only_update(
                PackageLayout.resolve(workflow_home),
                RuntimePaths(workflow_home),
                project,
                legacy_local_instructions=legacy_local_instructions,
            )
        )
    return _merge("project-update", plans)


def plan_platform_config(
    *,
    key: str,
    value: str,
    codex_home: Path,
    opencode_home: Path,
    platforms: list[str],
    claude_home: Path | None = None,
) -> OperationPlan:
    plans: list[OperationPlan] = []
    if "codex" in platforms:
        if key in ("orch", "senior"):
            plans.append(plan_model_config(_codex_runtime_paths(codex_home), key, value))
        elif len(platforms) == 1:
            raise ValidationError(
                f"key {key!r} is not a Codex model key; "
                "pass --platform opencode or --platform claude for worker-role models"
            )
        else:
            plans.append(
                OperationPlan(
                    "config",
                    [],
                    [],
                    [],
                    {
                        "platform": "codex",
                        "key": key,
                        "note": "Codex worker models other than Senior Executor are fixed.",
                    },
                )
            )
    if "opencode" in platforms:
        adapter = adapter_for("opencode", opencode_home=opencode_home)
        if not opencode_is_installed(adapter):
            raise ValidationError(
                "OpenCode Vision is not installed; complete the OpenCode bootstrap first"
            )
        if key == "orch":
            plans.append(
                OperationPlan(
                    "config",
                    [],
                    [],
                    [],
                    {
                        "platform": "opencode",
                        "key": key,
                        "note": "OpenCode owns the main-session model; no change was made.",
                    },
                )
            )
        elif key == "senior" and value in MODEL_TARGETS:
            # The Codex command form (`vision --config senior sol|luna`) also
            # runs for `both`; OpenCode keeps its native model mapping until a
            # native id is supplied.
            plans.append(
                OperationPlan(
                    "config",
                    [],
                    [],
                    [],
                    {
                        "platform": "opencode",
                        "key": key,
                        "note": "OpenCode worker models use native provider/model ids; skipped.",
                    },
                )
            )
        else:
            role = "senior_executor" if key == "senior" else key
            if role not in WORKER_ROLES:
                raise ValidationError(f"unsupported OpenCode worker role: {key!r}")
            mutation = adapter.set_worker_model(role, value)
            layout = PackageLayout.resolve(adapter.runtime_paths().workflow_home)
            specs = load_worker_specs(layout.workers, layout.agent_templates)
            if role not in specs:
                raise ValidationError(f"canonical worker role is missing: {role}")
            agent_mutation = adapter.install_worker(specs[role], model=value)[0]
            plans.append(
                OperationPlan(
                    "config",
                    [mutation, agent_mutation],
                    [],
                    [],
                    {
                        "platform": "opencode",
                        "key": key,
                        "value": value,
                        "model": value,
                    },
                )
            )
    if "claude" in platforms:
        adapter = _claude_adapter(claude_home)
        if not claude_is_installed(adapter):
            raise ValidationError(
                "Claude Code Vision is not installed; complete the Claude Code bootstrap first"
            )
        if key == "orch":
            plans.append(
                OperationPlan(
                    "config",
                    [],
                    [],
                    [],
                    {
                        "platform": "claude",
                        "key": key,
                        "note": "Claude Code owns the main-session model; no change was made.",
                    },
                )
            )
        else:
            role = "senior_executor" if key == "senior" else key
            if role not in WORKER_ROLES:
                raise ValidationError(f"unsupported Claude Code worker role: {key!r}")
            model = CLAUDE_MODEL_TARGETS.get(value, parse_claude_model(value))
            mutation = adapter.set_worker_model(role, model)
            layout = PackageLayout.resolve(adapter.runtime_paths().workflow_home)
            specs = load_worker_specs(layout.workers, layout.agent_templates)
            if role not in specs:
                raise ValidationError(f"canonical worker role is missing: {role}")
            agent_mutation = adapter.install_worker(specs[role], model=model)[0]
            plans.append(
                OperationPlan(
                    "config",
                    [mutation, agent_mutation],
                    [],
                    [],
                    {
                        "platform": "claude",
                        "key": key,
                        "value": value,
                        "model": model,
                    },
                )
            )
    return _merge("config", plans)


def resolve_platforms(
    selection: str | None,
    *,
    codex_home: Path,
    opencode_home: Path,
    prompt: bool = True,
    claude_home: Path | None = None,
) -> list[str]:
    """Resolve the platform selection, preferring recorded ownership."""

    if selection:
        return expand_selection(selection)
    installed = installed_platforms(
        codex_home=codex_home, opencode_home=opencode_home, claude_home=claude_home
    )
    if installed:
        return installed
    if prompt and _interactive():
        from .platforms import detect_platforms

        detected = detect_platforms(
            codex_home=codex_home, opencode_home=opencode_home, claude_home=claude_home
        )
        if len(detected) > 1:
            chosen = _prompt_platform()
            if chosen:
                return chosen
        if detected:
            return detected
    return ["codex"]


def _interactive() -> bool:
    import sys

    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def _prompt_platform() -> list[str] | None:
    print("Install Vision for:")
    print("> Codex")
    print("  OpenCode")
    print("  Claude Code")
    print("  Both (Codex + OpenCode)")
    print("  All (Codex + OpenCode + Claude Code)")
    try:
        answer = input("Select [codex/opencode/claude/both/all]: ").strip().lower()
    except EOFError:
        return None
    mapping = {
        "codex": ["codex"],
        "1": ["codex"],
        "opencode": ["opencode"],
        "2": ["opencode"],
        "claude": ["claude"],
        "3": ["claude"],
        "both": ["codex", "opencode"],
        "4": ["codex", "opencode"],
        "all": ["codex", "opencode", "claude"],
        "5": ["codex", "opencode", "claude"],
    }
    return mapping.get(answer)
