"""Persistent update-backup planning."""

from __future__ import annotations

from pathlib import Path

from .layout import USER_STATE, ProjectPaths, RuntimePaths
from .plan import read_json, read_string_list
from .transaction import Mutation


def append_backup_mutations(
    mutations: list[Mutation],
    backup_root: Path,
    runtime: RuntimePaths,
    project: ProjectPaths,
) -> None:
    targets = [
        path
        for path in (runtime.user_agents, runtime.config_toml)
        if path.is_file()
    ]
    if runtime.runtime.is_dir():
        targets.extend(
            path
            for path in runtime.runtime.rglob("*")
            if path.is_file()
            and ".backups" not in path.parts
            and ".source_backup" not in path.parts
        )
    if runtime.agents.is_dir():
        targets.extend(path for path in runtime.agents.glob("*.toml") if path.is_file())
    state = read_json(runtime.runtime / USER_STATE, default={})
    for skill in read_string_list(state, "owned_skills"):
        if not skill or Path(skill).name != skill:
            continue
        skill_root = runtime.skills / skill
        if skill_root.is_dir():
            targets.extend(path for path in skill_root.rglob("*") if path.is_file())
    targets.extend(
        path
        for path in (
            project.active,
            project.disabled,
            project.personalization,
            project.state,
        )
        if path.is_file()
    )
    seen: set[Path] = set()
    for source in targets:
        resolved = source.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_relative_to(source, runtime.codex_home):
            relative = Path("user") / source.relative_to(runtime.codex_home)
        else:
            relative = Path("project") / source.relative_to(project.root)
        mutations.append(Mutation(backup_root / relative, source.read_bytes()))


def append_project_backup_mutations(
    mutations: list[Mutation],
    backup_root: Path,
    project: ProjectPaths,
    project_mutations: list[Mutation],
) -> None:
    """Back up only existing project files affected by a project-only update."""

    seen: set[Path] = set()
    for mutation in project_mutations:
        source = mutation.path
        if source in seen or not source.is_file():
            continue
        seen.add(source)
        relative = source.relative_to(project.root)
        mutations.append(
            Mutation(backup_root / "project" / relative, source.read_bytes())
        )


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
