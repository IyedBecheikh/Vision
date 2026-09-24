"""Shared platform contract for Vision runtime backends.

Vision owns one workflow. A platform adapter owns only the client-specific
resources that realize that workflow: where the runtime lives, how a canonical
worker role is rendered as a native subagent, how the global instruction region
is installed, which platform configuration is patched, and which installed
resources Vision may remove again.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from ..errors import WorkflowError


class PlatformError(WorkflowError):
    """A platform operation violates the workflow contract."""


@dataclass(frozen=True)
class PlatformPaths:
    """Resolved, platform-neutral locations for one client installation."""

    platform: str
    client_home: Path
    workflow_home: Path
    agents_dir: Path
    skills_dir: Path
    commands_dir: Path
    instructions_file: Path
    config_file: Path
    state_file: Path


@dataclass(frozen=True)
class WorkerSpec:
    """One canonical worker role, independent of the target client."""

    role: str
    description: str
    instructions: str
    model_target: str
    reasoning_effort: str
    sandbox_mode: str = "workspace-write"

    @property
    def read_only(self) -> bool:
        return self.sandbox_mode == "read-only"


@dataclass
class SessionUsage:
    """A platform-neutral token-usage summary for one reporting row."""

    agent: str
    quantity: int = 0
    rollouts: int = 0
    cached_input_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, other: "SessionUsage") -> None:
        self.quantity += other.quantity
        self.rollouts += other.rollouts
        self.cached_input_tokens += other.cached_input_tokens
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


class PlatformAdapter(ABC):
    """Contract implemented by every Vision runtime backend."""

    platform: ClassVar[str]

    @abstractmethod
    def runtime_paths(self) -> PlatformPaths:
        """Return the resolved paths owned by this platform installation."""

    @abstractmethod
    def install_global_instructions(self, package: Any) -> list[Any]:
        """Return mutations that install the shared policy region."""

    @abstractmethod
    def render_worker(self, spec: WorkerSpec, *, model: str | None = None) -> str:
        """Render one canonical worker role in this platform's native format."""

    @abstractmethod
    def install_worker(self, spec: WorkerSpec, *, model: str | None = None) -> list[Any]:
        """Return mutations that materialize one worker role."""

    @abstractmethod
    def install_skill(self, skill: str, source_root: Path) -> list[Any]:
        """Return mutations that install one workflow-owned skill."""

    @abstractmethod
    def install_commands(self) -> list[Any]:
        """Return mutations that install Vision's native command surface."""

    @abstractmethod
    def remove_commands(self, state: dict[str, Any]) -> tuple[list[Any], list[Path], list[str]]:
        """Return mutations, cleanup directories, and warnings for command removal."""

    @abstractmethod
    def validate_commands(self) -> list[str]:
        """Return the installed Vision command names, raising on owned drift."""

    @abstractmethod
    def patch_platform_config(self, text: str, *, state: dict[str, Any] | None = None) -> str:
        """Return the platform configuration after Vision-owned settings."""

    @abstractmethod
    def remove_owned_resources(self, state: dict[str, Any]) -> tuple[list[Any], list[Path], list[str]]:
        """Return mutations, cleanup directories, and warnings for removal."""

    @abstractmethod
    def collect_session_usage(self, **options: Any) -> list[SessionUsage]:
        """Collect deployment-scoped usage through this platform's interface."""
