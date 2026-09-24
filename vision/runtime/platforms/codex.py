"""Codex runtime backend.

The adapter preserves the installed Codex behavior exactly: the same
``~/.codex`` paths, TOML workers, ``config.toml`` keys, skill directory, and
managed ``AGENTS.md`` region. It delegates to the established lifecycle modules
so no Codex behavior changes when Vision gains a second backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..layout import RuntimePaths
from ..platform_settings import MODEL_TARGETS
from ..runtime_ops import (
    plan_codex_commands,
    plan_runtime_remove,
    plan_user_agents,
    remove_codex_commands,
    validate_codex_commands,
)
from ..workers import render_codex_worker
from .base import PlatformAdapter, PlatformPaths, SessionUsage, WorkerSpec


class CodexAdapter(PlatformAdapter):
    platform = "codex"

    def __init__(self, codex_home: Path) -> None:
        self.codex_home = codex_home.expanduser().resolve()
        self.runtime = RuntimePaths(self.codex_home)

    def runtime_paths(self) -> PlatformPaths:
        return PlatformPaths(
            platform=self.platform,
            client_home=self.codex_home,
            workflow_home=self.runtime.runtime,
            agents_dir=self.runtime.agents,
            skills_dir=self.runtime.skills,
            commands_dir=self.runtime.skills,
            instructions_file=self.runtime.user_agents,
            config_file=self.runtime.config_toml,
            state_file=self.runtime.runtime / "install_state.json",
        )

    def default_model(self, spec: WorkerSpec) -> str:
        return MODEL_TARGETS.get(spec.model_target, MODEL_TARGETS["luna"])

    def install_global_instructions(self, package: Any) -> list[Any]:
        return plan_user_agents(package, self.runtime)

    def render_worker(self, spec: WorkerSpec, *, model: str | None = None) -> str:
        return render_codex_worker(spec, model=model or self.default_model(spec))

    def install_worker(self, spec: WorkerSpec, *, model: str | None = None) -> list[Any]:
        from ..plan import text_mutation

        rendered = self.render_worker(spec, model=model)
        return [text_mutation(self.runtime.agents / f"{spec.role}.toml", rendered)]

    def install_skill(self, skill: str, source_root: Path) -> list[Any]:
        from ..plan import Mutation

        mutations: list[Any] = []
        target_root = self.runtime.skills / skill
        for source in sorted(source_root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                mutations.append(
                    Mutation(target_root / source.relative_to(source_root), source.read_bytes())
                )
        return mutations

    def install_commands(self) -> list[Any]:
        mutations, _ = plan_codex_commands(self.runtime)
        return mutations

    def remove_commands(self, state: dict[str, Any]) -> tuple[list[Any], list[Path], list[str]]:
        mutations, cleanup = remove_codex_commands(self.runtime, state)
        return mutations, cleanup, []

    def validate_commands(self) -> list[str]:
        return validate_codex_commands(self.runtime)

    def patch_platform_config(self, text: str, *, state: dict[str, Any] | None = None) -> str:
        from ..platform_settings import patch_codex_settings

        return patch_codex_settings(text)

    def remove_owned_resources(self, state: dict[str, Any]) -> tuple[list[Any], list[Path], list[str]]:
        return plan_runtime_remove(self.runtime)

    def collect_session_usage(self, **options: Any) -> list[SessionUsage]:
        from ..session_usage import collect_codex_usage

        options.setdefault("skills_dir", self.runtime.skills)
        return collect_codex_usage(**options)
