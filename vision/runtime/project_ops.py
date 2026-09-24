"""Project documentation, state, and legacy entry-point migration operations."""

from __future__ import annotations

from pathlib import Path

from . import RUNTIME_SCHEMA_VERSION
from .errors import ValidationError
from .layout import PROJECT_ID, PackageLayout, ProjectPaths
from .markers import (
    PROJECT_LOCAL,
    PROJECT_PERSONALIZATION,
    WORKFLOW_MANAGED,
    extract,
    replace,
)
from .plan import OperationPlan, json_mutation, read_json, text_mutation
from .transaction import Mutation


GITIGNORE_ENTRIES = (".vision_hidden_resources/",)
LEGACY_GITIGNORE_ENTRIES = (
    "agent_docs/",
    ".vision_hidden_resources/",
    "AGENTS.md",
)
GITIGNORE_MANAGED_START = "# vision-managed-start"
GITIGNORE_MANAGED_END = "# vision-managed-end"
BOOTSTRAP_DOC_MARKER = "<!-- vision-bootstrap-template -->"
LEGACY_PROJECT_ROUTE_REFERENCES = (
    "agent_docs/workflows/medium_route.md",
    "agent_docs/workflows/heavy_route.md",
)


def _resolve_local_instructions(
    project: ProjectPaths,
    current: str,
    reviewed: str | None,
) -> str:
    """Reject unresolved legacy route imports or use an explicit reviewed body."""

    selected = current if reviewed is None else reviewed
    if reviewed is not None:
        reject_reserved_markers(reviewed)
    missing = [
        reference
        for reference in LEGACY_PROJECT_ROUTE_REFERENCES
        if reference in selected and not (project.root / reference).is_file()
    ]
    if missing:
        detail = ", ".join(missing)
        if reviewed is None:
            raise ValidationError(
                "existing project instructions reference missing legacy workflow route "
                f"files: {detail}; extract only reviewed project-local instructions and "
                "rerun with --legacy-local-instructions <file>"
            )
        raise ValidationError(
            f"reviewed project-local instructions still reference missing files: {detail}"
        )
    return selected


def _gitignore_block(entries: tuple[str, ...] = GITIGNORE_ENTRIES) -> str:
    return "\n".join((GITIGNORE_MANAGED_START, *entries, GITIGNORE_MANAGED_END))


def _gitignore_managed_range(lines: list[str]) -> tuple[int, int] | None:
    starts = [index for index, line in enumerate(lines) if line == GITIGNORE_MANAGED_START]
    ends = [index for index, line in enumerate(lines) if line == GITIGNORE_MANAGED_END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValidationError("project .gitignore has malformed workflow-managed markers")
    return starts[0], ends[0]


def _append_gitignore_block(current: str, entries: tuple[str, ...]) -> str:
    prefix = current.rstrip("\r\n")
    if prefix:
        prefix += "\n\n"
    return prefix + _gitignore_block(entries) + "\n"


def _remove_unmarked_gitignore_entries(
    current: str, entries: tuple[str, ...]
) -> str:
    retained = [
        line
        for line in current.splitlines()
        if not (line.strip() in entries and not line.lstrip().startswith("#"))
    ]
    rendered = "\n".join(retained).rstrip()
    return f"{rendered}\n" if rendered else ""


def _plan_gitignore(
    project: ProjectPaths, *, migrate_legacy: bool
) -> Mutation | None:
    """Add or normalize the removable workflow resource ignore rule."""

    path = project.gitignore
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValidationError(f"project .gitignore path is not a regular file: {path}")

    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = current.splitlines()
    managed_range = _gitignore_managed_range(lines)
    if managed_range is not None:
        start, end = managed_range
        managed_entries = lines[start + 1 : end]
        if (
            any(entry not in LEGACY_GITIGNORE_ENTRIES for entry in managed_entries)
            or len(managed_entries) != len(set(managed_entries))
        ):
            raise ValidationError("project .gitignore has invalid workflow-managed rules")
        outside_lines = lines[:start] + lines[end + 1 :]
        outside_entries = {
            line.strip()
            for line in outside_lines
            if line.strip() and not line.lstrip().startswith("#")
        }
        desired = [entry for entry in GITIGNORE_ENTRIES if entry not in outside_entries]
        if managed_entries == desired:
            return None
        rendered_lines = lines[: start + 1] + desired + lines[end:]
        rendered = "\n".join(rendered_lines).rstrip() + "\n"
        return text_mutation(path, rendered)

    existing = {
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }
    if migrate_legacy and set(LEGACY_GITIGNORE_ENTRIES).issubset(existing):
        return text_mutation(
            path,
            _append_gitignore_block(
                _remove_unmarked_gitignore_entries(current, LEGACY_GITIGNORE_ENTRIES),
                GITIGNORE_ENTRIES,
            ),
        )
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in existing]
    if not missing:
        return None
    return text_mutation(path, _append_gitignore_block(current, tuple(missing)))


def _plan_gitignore_remove(project: ProjectPaths) -> Mutation | None:
    path = project.gitignore
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValidationError(f"project .gitignore path is not a regular file: {path}")
    if not path.is_file():
        return None
    current = path.read_text(encoding="utf-8")
    lines = current.splitlines()
    managed_range = _gitignore_managed_range(lines)
    if managed_range is not None:
        start, end = managed_range
        retained = lines[:start] + lines[end + 1 :]
        rendered = "\n".join(retained).rstrip()
        return text_mutation(path, f"{rendered}\n" if rendered else "")
    existing = {
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }
    if set(LEGACY_GITIGNORE_ENTRIES).issubset(existing):
        return text_mutation(
            path,
            _remove_unmarked_gitignore_entries(current, LEGACY_GITIGNORE_ENTRIES),
        )
    return None


def _plan_source_cleanup(project: ProjectPaths) -> tuple[list[Mutation], list[Path]]:
    source = project.source_dir
    if source.is_symlink():
        raise ValidationError(
            f"refusing to remove symlinked package staging directory: {source}"
        )
    if not source.exists():
        return [], []
    if not source.is_dir():
        raise ValidationError(f"project package staging path is not a directory: {source}")

    mutations: list[Mutation] = []
    cleanup_dirs: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValidationError(
                f"refusing to remove symlink in package staging directory: {path}"
            )
        if path.is_dir():
            cleanup_dirs.append(path)
        elif path.is_file():
            mutations.append(Mutation(path, None))
        elif path.exists():
            raise ValidationError(
                f"package staging directory contains a non-file entry: {path}"
            )
    cleanup_dirs.append(source)
    return mutations, cleanup_dirs


def _native_instructions(personalization: str, local: str) -> str:
    sections = [section.strip() for section in (personalization, local) if section.strip()]
    return "\n\n".join(sections) + ("\n" if sections else "")


def _plan_legacy_entry_migration(
    project: ProjectPaths,
    *,
    installed_template: Path | None,
    legacy_local_instructions: str | None,
) -> tuple[list[Mutation], bool]:
    """Unwrap a workflow-owned project entry into an ordinary project AGENTS.md."""

    active_exists = project.active.exists()
    disabled_exists = project.disabled.exists()
    if active_exists and disabled_exists:
        raise ValidationError("both active and legacy disabled project entry points exist")
    for entry in (project.active, project.disabled):
        if entry.is_symlink() or (entry.exists() and not entry.is_file()):
            raise ValidationError(f"project entry point is not a regular file: {entry}")
    if not active_exists and not disabled_exists:
        if legacy_local_instructions is not None:
            raise ValidationError(
                "--legacy-local-instructions requires a legacy workflow entry point"
            )
        return [], False

    entry = project.active if active_exists else project.disabled
    current = entry.read_text(encoding="utf-8")
    if PROJECT_ID not in current:
        if disabled_exists:
            raise ValidationError("unrecognized legacy disabled entry point cannot be migrated")
        if legacy_local_instructions is not None:
            raise ValidationError(
                "--legacy-local-instructions requires a legacy workflow entry point"
            )
        return [], False

    if WORKFLOW_MANAGED.start in current and PROJECT_LOCAL.start in current:
        if installed_template is not None:
            template = installed_template.read_text(encoding="utf-8")
            if (
                WORKFLOW_MANAGED.start in template
                and extract(current, WORKFLOW_MANAGED)
                != extract(template, WORKFLOW_MANAGED)
            ):
                raise ValidationError(
                    "workflow-managed project region has local drift; move project rules "
                    "to the reviewed local instructions file"
                )
        personalization = extract(current, PROJECT_PERSONALIZATION)
        local = _resolve_local_instructions(
            project,
            extract(current, PROJECT_LOCAL),
            legacy_local_instructions,
        )
    elif PROJECT_PERSONALIZATION.start in current:
        personalization = extract(current, PROJECT_PERSONALIZATION)
        if installed_template is not None:
            template = installed_template.read_text(encoding="utf-8")
            if PROJECT_PERSONALIZATION.start in template:
                current_base = replace(current, PROJECT_PERSONALIZATION, "")
                template_base = replace(template, PROJECT_PERSONALIZATION, "")
                if current_base != template_base and legacy_local_instructions is None:
                    raise ValidationError(
                        "legacy project entry contains local edits; pass reviewed local "
                        "instructions explicitly"
                    )
        local = _resolve_local_instructions(
            project,
            legacy_local_instructions or "",
            legacy_local_instructions,
        )
    else:
        raise ValidationError("legacy workflow entry point has an unsupported marker format")

    rendered = _native_instructions(personalization, local)
    mutations: list[Mutation] = []
    if disabled_exists:
        if rendered:
            mutations.append(text_mutation(project.active, rendered))
        mutations.append(Mutation(project.disabled, None))
    elif rendered:
        mutations.append(text_mutation(project.active, rendered))
    else:
        mutations.append(Mutation(project.active, None))
    return mutations, True


def _documentation_mutations(
    package: PackageLayout, project: ProjectPaths
) -> tuple[list[Mutation], list[dict[str, object]]]:
    mutations: list[Mutation] = []
    sources = sorted(package.project_docs.glob("*.md"))
    framework = [source.name for source in sources]
    action_docs: list[str] = []
    created_docs: list[str] = []
    recovery_docs: list[str] = []
    for source in sources:
        target = project.docs / source.name
        if not target.exists():
            mutations.append(Mutation(target, source.read_bytes()))
            created_docs.append(source.name)
            action_docs.append(source.name)
        elif target.is_file() and BOOTSTRAP_DOC_MARKER in target.read_text(
            encoding="utf-8"
        ):
            recovery_docs.append(source.name)
            action_docs.append(source.name)
    actions: list[dict[str, object]] = [
        {
            "role": "archivist",
            "action": "initialize or verify the Project Documentation Framework",
            "required": True,
            "files": action_docs,
            "created_files": created_docs,
            "recovery_files": recovery_docs,
            "framework": framework,
            "required_context_files": [
                "project_structure.md",
                "project_overview.md",
                "project_core_tech.md",
            ],
        }
    ]
    return mutations, actions


def plan_project_install(
    package: PackageLayout,
    project: ProjectPaths,
    *,
    legacy_local_instructions: str | None = None,
) -> OperationPlan:
    prior_state = read_json(project.state, default={})
    migrations, migrated = _plan_legacy_entry_migration(
        project,
        installed_template=package.legacy_project_template,
        legacy_local_instructions=legacy_local_instructions,
    )
    mutations = list(migrations)
    warnings = (
        ["legacy workflow wrapper will be removed; project instructions remain in AGENTS.md"]
        if migrated
        else []
    )
    doc_mutations, actions = _documentation_mutations(package, project)
    mutations.extend(doc_mutations)
    state = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "workflow_version": package.version,
    }
    state_mutation = json_mutation(project.state, state)
    if not project.state.is_file() or project.state.read_bytes() != state_mutation.content:
        mutations.append(state_mutation)
    gitignore_mutation = _plan_gitignore(
        project, migrate_legacy=migrated or bool(prior_state)
    )
    if gitignore_mutation is not None:
        mutations.append(gitignore_mutation)
    if project.personalization.is_file():
        mutations.append(Mutation(project.personalization, None))
    cleanup_mutations, cleanup_dirs = _plan_source_cleanup(project)
    mutations.extend(cleanup_mutations)
    if cleanup_mutations:
        warnings.append(f"{project.source_dir} will be deleted after installation")
    return OperationPlan(
        "project-install",
        mutations,
        warnings,
        actions,
        cleanup_dirs=cleanup_dirs,
    )


def plan_project_update(
    installed: PackageLayout,
    incoming: PackageLayout,
    project: ProjectPaths,
    *,
    legacy_local_instructions: str | None,
) -> tuple[list[Mutation], list[str]]:
    prior_state = read_json(project.state, default={})
    migrations, migrated = _plan_legacy_entry_migration(
        project,
        installed_template=installed.legacy_project_template,
        legacy_local_instructions=legacy_local_instructions,
    )
    if not prior_state and not migrated:
        return [], ["current project is not workflow-installed; user-level update only"]

    mutations = list(migrations)
    state = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "workflow_version": incoming.version,
    }
    mutations.append(json_mutation(project.state, state))
    if project.personalization.is_file():
        mutations.append(Mutation(project.personalization, None))
    gitignore_mutation = _plan_gitignore(project, migrate_legacy=True)
    if gitignore_mutation is not None:
        mutations.append(gitignore_mutation)
    warnings = (
        ["legacy workflow wrapper will be removed; project instructions remain in AGENTS.md"]
        if migrated
        else []
    )
    return mutations, warnings


def plan_project_remove(
    project: ProjectPaths,
) -> tuple[list[Mutation], list[Path], list[str]]:
    migrations, migrated = _plan_legacy_entry_migration(
        project,
        installed_template=None,
        legacy_local_instructions=None,
    )
    mutations = list(migrations)
    warnings = ["project agent_docs/ and AGENTS.md are project-owned and will be preserved"]
    if migrated:
        warnings.append("legacy workflow wrapper will be removed from project AGENTS.md")

    gitignore_mutation = _plan_gitignore_remove(project)
    if gitignore_mutation is not None:
        mutations.append(gitignore_mutation)
        warnings.append("workflow-owned .gitignore rules will be removed")

    hidden_dir = project.workflow_dir
    if hidden_dir.is_symlink() or (hidden_dir.exists() and not hidden_dir.is_dir()):
        raise ValidationError(f"project hidden resource is not a directory: {hidden_dir}")

    planned = {mutation.path.resolve(strict=False) for mutation in mutations}
    cleanup_dirs: list[Path] = []
    legacy_resources = False
    if hidden_dir.is_dir():
        for path in sorted(hidden_dir.rglob("*")):
            if path.is_symlink():
                raise ValidationError(f"refusing to remove symlink in project resource: {path}")
            if path.is_dir():
                cleanup_dirs.append(path)
            elif path.is_file() and path.resolve(strict=False) not in planned:
                mutations.append(Mutation(path, None))
                planned.add(path.resolve(strict=False))
                if path not in (project.state, project.personalization, project.disabled):
                    legacy_resources = True
            elif path.exists() and not path.is_file():
                raise ValidationError(f"project resource contains a non-file entry: {path}")
        cleanup_dirs.append(hidden_dir)
    if legacy_resources:
        warnings.append("legacy project workflow resources will be permanently deleted")
    return mutations, cleanup_dirs, warnings


def reject_reserved_markers(text: str) -> None:
    reserved = [
        WORKFLOW_MANAGED.start,
        WORKFLOW_MANAGED.end,
        PROJECT_PERSONALIZATION.start,
        PROJECT_PERSONALIZATION.end,
        PROJECT_LOCAL.start,
        PROJECT_LOCAL.end,
    ]
    collisions = [marker for marker in reserved if marker in text]
    if collisions:
        raise ValidationError(f"existing AGENTS.md contains reserved markers: {collisions}")
