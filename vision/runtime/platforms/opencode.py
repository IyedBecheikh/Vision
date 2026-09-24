"""OpenCode runtime backend.

OpenCode owns provider authentication, credentials, available models, and main
session model selection. Vision only installs native Markdown subagents, the
shared global instruction region, and its own skill, then records ownership so
it can update or remove exactly what it created.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..commands import (
    COMMAND_NAMES,
    VISION_COMMANDS,
    command_marker_name,
    render_opencode_command,
)
from ..markers import (
    USER_MANAGED,
    append_region,
    extract,
    remove_region,
    replace,
    substitute_vision_home,
)
from ..plan import (
    Mutation,
    json_mutation,
    read_json,
    read_string_list,
    text_mutation,
)
from ..runtime_ops import validate_skill_owner
from ..workers import load_worker_specs
from .base import PlatformAdapter, PlatformPaths, SessionUsage, WorkerSpec


WORKER_FILE_MARKER = re.compile(r"^<!-- vision-worker: ([A-Za-z0-9_-]+) -->$", re.MULTILINE)
CONFIG_NAME = "config.json"
OWNED_EXCLUDED = frozenset(
    {"agents", ".source_backup", ".backups", CONFIG_NAME, "install_state.json"}
)
_REASONING_VARIANTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)


def default_opencode_home() -> Path:
    import os

    configured = os.environ.get("OPENCODE_HOME") or os.environ.get("OPENCODE_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "opencode"


def parse_model_id(value: str) -> tuple[str, str | None]:
    """Validate an OpenCode ``provider/model#variant`` model identifier."""

    raw = value.strip()
    if not raw:
        raise ValidationError("model id must not be empty")
    base, _, variant = raw.partition("#")
    provider, separator, model = base.partition("/")
    if not separator or not provider or not model or "/" in model:
        raise ValidationError(
            f"invalid OpenCode model id {value!r}; expected provider/model or provider/model#variant"
        )
    if variant and not re.fullmatch(r"[A-Za-z0-9._-]+", variant):
        raise ValidationError(f"invalid model variant in {value!r}")
    return base, (variant or None)


def render_opencode_worker(
    spec: WorkerSpec,
    *,
    model: str | None,
    home_display: str,
) -> str:
    """Render one canonical role as an OpenCode Markdown subagent."""

    lines = [
        "---",
        f"description: {spec.description}",
        "mode: subagent",
    ]
    if model:
        base, variant = parse_model_id(model)
        lines.append(f"model: {base}")
        if variant:
            if variant in _REASONING_VARIANTS:
                lines.append(f"reasoningEffort: {variant}")
            else:
                lines.append(f"variant: {variant}")
    permission = "deny" if spec.read_only else "allow"
    lines.extend(
        [
            "permission:",
            f"  edit: {permission}",
            f"  bash: {permission}",
            "  task: deny",
            "  webfetch: allow",
            "  websearch: allow",
            "---",
            "",
            f"<!-- vision-worker: {spec.role} -->",
            "",
        ]
    )
    instructions = substitute_vision_home(spec.instructions, home_display=home_display)
    lines.append(instructions)
    lines.append("")
    return "\n".join(lines)


class OpenCodeAdapter(PlatformAdapter):
    platform = "opencode"

    def __init__(self, opencode_home: Path) -> None:
        self.opencode_home = opencode_home.expanduser().resolve()
        self.home_display = "~/.config/opencode"

    def runtime_paths(self) -> PlatformPaths:
        workflow_home = self.opencode_home / "vision"
        return PlatformPaths(
            platform=self.platform,
            client_home=self.opencode_home,
            workflow_home=workflow_home,
            agents_dir=self.opencode_home / "agents",
            skills_dir=self.opencode_home / "skills",
            commands_dir=self.opencode_home / "commands",
            instructions_file=self.opencode_home / "AGENTS.md",
            config_file=self.opencode_home / "opencode.json",
            state_file=workflow_home / "install_state.json",
        )

    @property
    def vision_home_display(self) -> str:
        return f"{self.home_display}/vision"

    # -- worker models -------------------------------------------------

    def worker_models(self) -> dict[str, str]:
        path = self.runtime_paths().workflow_home / CONFIG_NAME
        data = read_json(path, default={}) if path.is_file() else {}
        models = data.get("worker_models", {})
        if not isinstance(models, dict):
            raise ValidationError("OpenCode worker_models configuration must be an object")
        result: dict[str, str] = {}
        for role, value in models.items():
            if isinstance(role, str) and isinstance(value, str) and value:
                parse_model_id(value)
                result[role] = value
        return result

    def set_worker_model(self, key: str, value: str) -> Mutation:
        parse_model_id(value)
        models = self.worker_models()
        models[key] = value
        return json_mutation(
            self.runtime_paths().workflow_home / CONFIG_NAME,
            {"worker_models": dict(sorted(models.items()))},
        )

    # -- PlatformAdapter -----------------------------------------------

    def install_global_instructions(self, package: Any) -> list[Any]:
        source = (package.operate / "user_AGENTS.md").read_text(encoding="utf-8")
        managed = substitute_vision_home(
            extract(source, USER_MANAGED), home_display=self.vision_home_display
        )
        path = self.runtime_paths().instructions_file
        if path.is_file():
            current = path.read_text(encoding="utf-8")
            if USER_MANAGED.start in current or USER_MANAGED.end in current:
                rendered = replace(current, USER_MANAGED, managed)
            else:
                rendered = append_region(current, USER_MANAGED, managed)
        else:
            rendered = append_region("", USER_MANAGED, managed)
        return [text_mutation(path, rendered)]

    def render_worker(self, spec: WorkerSpec, *, model: str | None = None) -> str:
        if model is None:
            model = self.worker_models().get(spec.role)
        return render_opencode_worker(
            spec, model=model, home_display=self.vision_home_display
        )

    def install_worker(self, spec: WorkerSpec, *, model: str | None = None) -> list[Any]:
        rendered = self.render_worker(spec, model=model)
        return [text_mutation(self.runtime_paths().agents_dir / f"{spec.role}.md", rendered)]

    def install_skill(self, skill: str, source_root: Path) -> list[Any]:
        mutations: list[Any] = []
        target_root = self.runtime_paths().skills_dir / skill
        for source in sorted(source_root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                mutations.append(
                    Mutation(target_root / source.relative_to(source_root), source.read_bytes())
                )
        return mutations

    def install_commands(self) -> list[Any]:
        mutations, _ = plan_opencode_commands(self, {})
        return mutations

    def remove_commands(self, state: dict[str, Any]) -> tuple[list[Any], list[Path], list[str]]:
        mutations, cleanup = _remove_opencode_commands(self, state)
        warnings = ["unrelated OpenCode commands will be preserved"]
        return mutations, cleanup, warnings

    def validate_commands(self) -> list[str]:
        return _validate_opencode_commands(self)

    def patch_platform_config(self, text: str, *, state: dict[str, Any] | None = None) -> str:
        """OpenCode owns its config; Vision preserves it byte for byte."""

        return text

    def remove_owned_resources(self, state: dict[str, Any]) -> tuple[list[Any], list[Path], list[str]]:
        adapter = self
        mutations: list[Any] = []
        cleanup_dirs: list[Path] = []
        warnings = [
            "unrelated OpenCode agents will be preserved",
            "unrelated OpenCode skills and opencode.json will be preserved",
        ]
        paths = adapter.runtime_paths()

        for role in read_string_list(state, "owned_workers"):
            target = paths.agents_dir / f"{role}.md"
            if not target.exists():
                continue
            _validate_worker_owner(target, role)
            mutations.append(Mutation(target, None))
        cleanup_dirs.append(paths.agents_dir)

        for skill in read_string_list(state, "owned_skills"):
            target_root = paths.skills_dir / skill
            if not target_root.exists():
                continue
            validate_skill_owner(target_root, skill)
            for path in sorted(target_root.rglob("*")):
                if path.is_file():
                    mutations.append(Mutation(path, None))
                elif path.is_dir():
                    cleanup_dirs.append(path)
            cleanup_dirs.append(target_root)
        cleanup_dirs.append(paths.skills_dir)

        command_mutations, command_cleanup = _remove_opencode_commands(adapter, state)
        mutations.extend(command_mutations)
        cleanup_dirs.extend(command_cleanup)
        warnings.append("unrelated OpenCode commands will be preserved")

        if paths.instructions_file.is_file():
            current = paths.instructions_file.read_text(encoding="utf-8")
            if USER_MANAGED.start in current or USER_MANAGED.end in current:
                rendered = remove_region(current, USER_MANAGED)
                mutations.append(
                    Mutation(
                        paths.instructions_file,
                        rendered.encode("utf-8") if rendered else None,
                    )
                )

        if paths.workflow_home.is_dir():
            for path in sorted(paths.workflow_home.rglob("*")):
                if path.is_symlink():
                    raise ValidationError(f"refusing to remove symlink in workflow runtime: {path}")
                if path.is_dir():
                    cleanup_dirs.append(path)
                elif path.is_file():
                    mutations.append(Mutation(path, None))
                elif path.exists():
                    raise ValidationError(f"workflow runtime contains a non-file entry: {path}")
            cleanup_dirs.append(paths.workflow_home)
            warnings.append(
                f"all files under {paths.workflow_home} (including source and update backups) will be permanently deleted"
            )
        return mutations, cleanup_dirs, warnings

    def collect_session_usage(self, **options: Any) -> list[SessionUsage]:
        from ..session_usage import collect_opencode_usage

        options.setdefault("skills_dir", self.runtime_paths().skills_dir)
        return collect_opencode_usage(**options)


def _validate_worker_owner(path: Path, worker: str) -> None:
    text = path.read_text(encoding="utf-8")
    match = WORKER_FILE_MARKER.search(text)
    if match is None or match.group(1) != worker:
        raise ValidationError(f"refusing to remove non-owned OpenCode agent file: {path}")


def _validate_open_command_owner(path: Path, name: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"OpenCode command path is not a regular file: {path}")
    if command_marker_name(path.read_text(encoding="utf-8")) != name:
        raise ValidationError(f"OpenCode command ownership marker missing or wrong: {path}")


def plan_opencode_commands(
    adapter: OpenCodeAdapter, previous_state: dict[str, Any]
) -> tuple[list[Any], list[Path]]:
    """Materialize Vision's OpenCode slash commands without touching other files."""

    paths = adapter.runtime_paths()
    mutations: list[Any] = []
    cleanup_dirs: list[Path] = [paths.commands_dir]
    previous_owned = set(read_string_list(previous_state, "owned_commands"))
    for spec in VISION_COMMANDS:
        target = paths.commands_dir / f"{spec.name}.md"
        if target.exists():
            _validate_open_command_owner(target, spec.name)
        mutations.append(
            text_mutation(
                target,
                render_opencode_command(spec, home_display=adapter.vision_home_display),
            )
        )
    for name in sorted(previous_owned - set(COMMAND_NAMES)):
        target = paths.commands_dir / f"{name}.md"
        if target.exists():
            _validate_open_command_owner(target, name)
            mutations.append(Mutation(target, None))
    return mutations, cleanup_dirs


def _remove_opencode_commands(
    adapter: OpenCodeAdapter, state: dict[str, Any]
) -> tuple[list[Any], list[Path]]:
    paths = adapter.runtime_paths()
    mutations: list[Any] = []
    cleanup_dirs: list[Path] = [paths.commands_dir]
    for name in read_string_list(state, "owned_commands"):
        target = paths.commands_dir / f"{name}.md"
        if target.exists():
            _validate_open_command_owner(target, name)
            mutations.append(Mutation(target, None))
    return mutations, cleanup_dirs


def _validate_opencode_commands(adapter: OpenCodeAdapter) -> list[str]:
    commands_dir = adapter.runtime_paths().commands_dir
    found: list[str] = []
    if not commands_dir.is_dir():
        return found
    for target in sorted(commands_dir.glob("*.md")):
        if target.is_symlink() or not target.is_file():
            continue
        marker = command_marker_name(target.read_text(encoding="utf-8"))
        candidate = target.stem
        if marker is None:
            if candidate in COMMAND_NAMES:
                raise ValidationError(
                    f"Vision OpenCode command is missing its ownership marker: {target}"
                )
            continue
        if target.name != f"{marker}.md" or marker not in COMMAND_NAMES:
            raise ValidationError(f"unexpected Vision OpenCode command file: {target}")
        found.append(marker)
    return found


# -- lifecycle planning helpers -------------------------------------------


def plan_opencode_runtime(
    package: Any,
    adapter: OpenCodeAdapter,
    *,
    platforms: list[str],
    previous_state: dict[str, Any] | None = None,
) -> tuple[list[Any], set[str], list[Path]]:
    """Materialize one OpenCode installation as a set of mutations."""

    paths = adapter.runtime_paths()
    previous_state = previous_state or {}
    mutations: list[Any] = []
    owned: set[str] = set()

    for source in sorted(package.root.rglob("*")):
        relative = source.relative_to(package.root)
        if (
            relative.parts[0] in OWNED_EXCLUDED
            or "__pycache__" in relative.parts
            or source.suffix == ".pyc"
            or not source.is_file()
        ):
            continue
        data = source.read_bytes()
        if source.suffix == ".md":
            data = substitute_vision_home(
                data.decode("utf-8"), home_display=adapter.vision_home_display
            ).encode("utf-8")
        mutations.append(Mutation(paths.workflow_home / relative, data))
        owned.add(relative.as_posix())

    specs = load_worker_specs(package.workers, package.agent_templates)
    models = adapter.worker_models()
    for role in sorted(specs):
        mutations.append(
            Mutation(
                paths.agents_dir / f"{role}.md",
                adapter.render_worker(specs[role], model=models.get(role)).encode("utf-8"),
            )
        )
    for role in sorted(set(read_string_list(previous_state, "owned_workers")) - set(specs)):
        target = paths.agents_dir / f"{role}.md"
        if target.exists():
            _validate_worker_owner(target, role)
            mutations.append(Mutation(target, None))

    skill_mutations, skill_cleanup = plan_opencode_skills(adapter, package, previous_state)
    mutations.extend(skill_mutations)
    command_mutations, command_cleanup = plan_opencode_commands(adapter, previous_state)
    mutations.extend(command_mutations)
    skill_cleanup.extend(command_cleanup)
    mutations.extend(adapter.install_global_instructions(package))

    config = {"worker_models": dict(sorted(models.items()))}
    config_path = paths.workflow_home / CONFIG_NAME
    current_config = read_json(config_path, default={}) if config_path.is_file() else {}
    if current_config != config:
        mutations.append(json_mutation(config_path, config))

    state = {
        "schema_version": 2,
        "version": package.version,
        "platform": adapter.platform,
        "platforms": sorted(set(platforms)),
        "owned_runtime_files": sorted(owned),
        "owned_workers": sorted(specs),
        "owned_skills": sorted(package.skill_names),
        "owned_commands": sorted(COMMAND_NAMES),
    }
    mutations.append(json_mutation(paths.state_file, state))
    return mutations, owned, skill_cleanup


def plan_opencode_skills(
    adapter: OpenCodeAdapter,
    package: Any,
    previous_state: dict[str, Any],
) -> tuple[list[Any], list[Path]]:
    paths = adapter.runtime_paths()
    mutations: list[Any] = []
    cleanup_dirs: list[Path] = []
    incoming = package.skill_names
    for skill in sorted(incoming):
        source_root = package.skill_templates / skill
        target_root = paths.skills_dir / skill
        if target_root.exists():
            validate_skill_owner(target_root, skill)
        source_files = {
            source.relative_to(source_root): source
            for source in source_root.rglob("*")
            if source.is_file() and "__pycache__" not in source.parts
        }
        target_files = (
            {
                target.relative_to(target_root): target
                for target in target_root.rglob("*")
                if target.is_file()
            }
            if target_root.is_dir()
            else {}
        )
        for relative, source in sorted(source_files.items(), key=lambda item: str(item[0])):
            mutations.append(Mutation(target_root / relative, source.read_bytes()))
        for relative, target in sorted(target_files.items(), key=lambda item: str(item[0])):
            if relative not in source_files:
                mutations.append(Mutation(target, None))
        cleanup_dirs.extend(path for path in target_root.rglob("*") if path.is_dir())

    for skill in sorted(set(read_string_list(previous_state, "owned_skills")) - incoming):
        target_root = paths.skills_dir / skill
        if not target_root.exists():
            continue
        validate_skill_owner(target_root, skill)
        for path in target_root.rglob("*"):
            if path.is_file():
                mutations.append(Mutation(path, None))
            elif path.is_dir():
                cleanup_dirs.append(path)
        cleanup_dirs.append(target_root)
    return mutations, cleanup_dirs


def read_installed_state(adapter: OpenCodeAdapter) -> dict[str, Any]:
    path = adapter.runtime_paths().state_file
    return read_json(path, default={}) if path.is_file() else {}


def opencode_is_installed(adapter: OpenCodeAdapter) -> bool:
    return (adapter.runtime_paths().workflow_home / "operate" / "VERSION").is_file()
