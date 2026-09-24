"""Platform registry for Vision's Codex and OpenCode runtime backends."""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import (
    PlatformAdapter,
    PlatformError,
    PlatformPaths,
    SessionUsage,
    WorkerSpec,
)


SUPPORTED_PLATFORMS: tuple[str, ...] = ("codex", "opencode")
PLATFORM_CHOICES: tuple[str, ...] = ("codex", "opencode", "both")


def default_opencode_home() -> Path:
    from .opencode import default_opencode_home as resolve

    return resolve()


def _resolve_home(value: Path | str | None, default: Path) -> Path:
    if value is None:
        return default.expanduser()
    return Path(value).expanduser()


def adapter_for(
    platform: str,
    *,
    codex_home: Path | str | None = None,
    opencode_home: Path | str | None = None,
) -> PlatformAdapter:
    if platform == "codex":
        from .codex import CodexAdapter

        return CodexAdapter(_resolve_home(codex_home, Path.home() / ".codex").resolve())
    if platform == "opencode":
        from .opencode import OpenCodeAdapter

        return OpenCodeAdapter(_resolve_home(opencode_home, default_opencode_home()).resolve())
    raise PlatformError(f"unsupported platform: {platform!r}")


def expand_selection(selection: str) -> list[str]:
    if selection == "both":
        return list(SUPPORTED_PLATFORMS)
    if selection in SUPPORTED_PLATFORMS:
        return [selection]
    raise PlatformError(
        f"unsupported platform: {selection!r}; expected one of {list(PLATFORM_CHOICES)}"
    )


def detect_platforms(
    *,
    codex_home: Path | str | None = None,
    opencode_home: Path | str | None = None,
) -> list[str]:
    """Detect supported clients from their config home or executable."""

    detected: list[str] = []
    codex = _resolve_home(codex_home, Path.home() / ".codex")
    if codex.exists() or shutil.which("codex"):
        detected.append("codex")
    opencode = _resolve_home(opencode_home, default_opencode_home())
    if opencode.exists() or shutil.which("opencode"):
        detected.append("opencode")
    return detected


__all__ = [
    "PlatformAdapter",
    "PlatformError",
    "PlatformPaths",
    "SessionUsage",
    "WorkerSpec",
    "SUPPORTED_PLATFORMS",
    "PLATFORM_CHOICES",
    "adapter_for",
    "default_opencode_home",
    "detect_platforms",
    "expand_selection",
]
