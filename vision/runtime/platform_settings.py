"""Fixed Codex platform settings owned by the workflow."""

from __future__ import annotations

import re

from ._toml import tomllib
from .errors import ValidationError


MODEL_TARGETS: dict[str, str] = {
    "sol": "gpt-6-sol",
    "luna": "gpt-6-luna",
}

DEFAULT_ORCHESTRATOR_TARGET = "sol"
DEFAULT_SENIOR_TARGET = "sol"

_AGENT_MODEL_LINE = re.compile(
    r'^[ \t]*model[ \t]*=[ \t]*"[^"]*"[ \t]*$', re.MULTILINE
)


def _model_for(target: str) -> str:
    if target not in MODEL_TARGETS:
        raise ValidationError(
            f"unsupported model target: {target!r}; "
            f"expected one of {sorted(MODEL_TARGETS)}"
        )
    return MODEL_TARGETS[target]


def _require_toml(text: str, *, label: str) -> None:
    if not text.strip():
        return
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"{label} is invalid TOML: {error}") from error


def _validated_config(lines: list[str]) -> str:
    rendered = "\n".join(lines).rstrip() + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"generated Codex config is invalid TOML: {error}") from error
    return rendered


def patch_orchestrator_model(text: str, target: str) -> str:
    """Set the orchestrator (main-agent) model without replacing user settings."""

    model = _model_for(target)
    _require_toml(text, label="existing Codex config")
    lines = _patch_top_level_key(text.splitlines(), "model", f'"{model}"')
    lines = _patch_section(
        lines,
        "vision",
        {"orchestrator": f'"{target}"', "orchestrator_model": f'"{model}"'},
    )
    return _validated_config(lines)


def patch_vision_settings(text: str, **updates: str) -> str:
    """Record workflow model choices without changing the top-level model."""

    _require_toml(text, label="existing Codex config")
    lines = _patch_section(
        text.splitlines(), "vision", {key: f'"{value}"' for key, value in updates.items()}
    )
    return _validated_config(lines)


def patch_worker_model(text: str, target: str) -> str:
    """Set one worker definition's model, preserving its reasoning effort."""

    model = _model_for(target)
    _require_toml(text, label="worker definition")
    if not _AGENT_MODEL_LINE.search(text):
        raise ValidationError("worker definition has no model assignment")
    rendered = _AGENT_MODEL_LINE.sub(f'model = "{model}"', text, count=1)
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(
            f"generated worker definition is invalid TOML: {error}"
        ) from error
    return rendered


def read_config_target(text: str, key: str) -> str | None:
    """Read a recorded model target from the workflow-owned [vision] section."""

    if not text.strip():
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    vision = data.get("vision")
    if not isinstance(vision, dict):
        return None
    value = vision.get(key)
    if isinstance(value, str) and value in MODEL_TARGETS:
        return value
    return None


def has_top_level_key(text: str, key: str) -> bool:
    if not text.strip():
        return False
    lines = text.splitlines()
    end = next(
        (index for index, line in enumerate(lines) if _SECTION.match(line)),
        len(lines),
    )
    return any(
        (match := _KEY.match(lines[index])) and match.group(1) == key
        for index in range(end)
    )


def _patch_top_level_key(lines: list[str], key: str, value: str) -> list[str]:
    """Replace or insert a key above the first TOML table."""

    end = next(
        (index for index, line in enumerate(lines) if _SECTION.match(line)),
        len(lines),
    )
    matches = [
        index
        for index in range(end)
        if (match := _KEY.match(lines[index])) and match.group(1) == key
    ]
    if len(matches) > 1:
        raise ValidationError(f"duplicate top-level TOML key {key!r}")
    if matches:
        result = list(lines)
        result[matches[0]] = f"{key} = {value}"
        return result
    result = list(lines)
    result.insert(0, f"{key} = {value}")
    return result


def patch_codex_settings(text: str) -> str:
    """Apply the workflow's fixed platform settings without replacing user settings."""

    if text.strip():
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise ValidationError(f"existing Codex config is invalid TOML: {error}") from error
    sections: dict[str, dict[str, str]] = {
        "agents": {"enabled": "true"},
        "features": {"multi_agent": "true"},
        "features.multi_agent_v2": {
            "enabled": "true",
            "min_wait_timeout_ms": "300000",
            "default_wait_timeout_ms": "300000",
            "max_wait_timeout_ms": "1800000",
        },
    }
    lines = _remove_owned_keys(text.splitlines(), _LEGACY_OWNED_KEYS)
    for section, values in sections.items():
        lines = _patch_section(lines, section, values)
    rendered = "\n".join(lines).rstrip() + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"generated Codex config is invalid TOML: {error}") from error
    return rendered


_SECTION = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")
_KEY = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


def _patch_section(lines: list[str], section: str, values: dict[str, str]) -> list[str]:
    headers = [
        index
        for index, line in enumerate(lines)
        if (_SECTION.match(line) and _SECTION.match(line).group(1) == section)
    ]
    if len(headers) > 1:
        raise ValidationError(f"duplicate TOML section [{section}]")
    if not headers:
        result = list(lines)
        if result and result[-1].strip():
            result.append("")
        result.append(f"[{section}]")
        result.extend(f"{key} = {value}" for key, value in values.items())
        return result
    start = headers[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if _SECTION.match(lines[index])),
        len(lines),
    )
    found: dict[str, int] = {}
    result = list(lines)
    for index in range(start + 1, end):
        match = _KEY.match(result[index])
        if match and match.group(1) in values:
            key = match.group(1)
            if key in found:
                raise ValidationError(f"duplicate workflow-owned TOML key [{section}].{key}")
            found[key] = index
            result[index] = f"{key} = {values[key]}"
    missing = [key for key in values if key not in found]
    result[end:end] = [f"{key} = {values[key]}" for key in missing]
    return result


_LEGACY_OWNED_KEYS: dict[str, set[str]] = {
    "agents": {"max_concurrent_threads_per_session", "max_threads"},
    "features.multi_agent_v2": {
        "max_concurrent_threads_per_session",
        "hide_spawn_agent_metadata",
        "tool_namespace",
    },
}


_OWNED_KEYS: dict[str, set[str]] = {
    "agents": {"enabled", "max_concurrent_threads_per_session", "max_threads"},
    "features": {"multi_agent"},
    "features.multi_agent_v2": {
        *_LEGACY_OWNED_KEYS["features.multi_agent_v2"],
        "enabled",
        "min_wait_timeout_ms",
        "default_wait_timeout_ms",
        "max_wait_timeout_ms",
    },
    "vision": {"orchestrator", "orchestrator_model", "senior", "senior_model"},
}


def _remove_owned_keys(
    lines: list[str], owned_keys: dict[str, set[str]]
) -> list[str]:
    """Remove selected keys while retaining unrelated keys in the same tables."""

    result: list[str] = []
    index = 0
    while index < len(lines):
        header = _SECTION.match(lines[index])
        if header is None or header.group(1) not in owned_keys:
            result.append(lines[index])
            index += 1
            continue

        section = header.group(1)
        end = next(
            (
                position
                for position in range(index + 1, len(lines))
                if _SECTION.match(lines[position])
            ),
            len(lines),
        )
        owned = owned_keys[section]
        retained = [
            line
            for line in lines[index + 1 : end]
            if (match := _KEY.match(line)) is None or match.group(1) not in owned
        ]
        if any(line.strip() for line in retained):
            result.append(lines[index])
            result.extend(retained)
        index = end
    return result


def remove_workflow_owned_settings(text: str) -> str:
    """Remove only the Codex platform settings owned by this workflow."""

    if not text.strip():
        return ""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"existing Codex config is invalid TOML: {error}") from error

    result = _remove_owned_keys(text.splitlines(), _OWNED_KEYS)
    rendered = "\n".join(result).rstrip()
    if rendered:
        rendered += "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"generated Codex config is invalid TOML: {error}") from error
    return rendered
