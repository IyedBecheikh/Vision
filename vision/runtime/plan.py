"""Operation plans and shared mutation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .transaction import Mutation, apply as apply_transaction, summarize


@dataclass
class OperationPlan:
    operation: str
    mutations: list[Mutation]
    warnings: list[str]
    agent_actions: list[dict[str, Any]]
    details: dict[str, Any] = field(default_factory=dict)
    cleanup_dirs: list[Path] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            **summarize(self.mutations),
            "warnings": self.warnings,
            "agent_actions": self.agent_actions,
            "details": self.details,
        }

    def apply(self) -> None:
        apply_transaction(self.mutations)
        for directory in sorted(
            set(self.cleanup_dirs), key=lambda path: len(path.parts), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                pass


def text_mutation(path: Path, text: str) -> Mutation:
    return Mutation(path, text.encode("utf-8"))


def json_mutation(path: Path, value: dict[str, Any]) -> Mutation:
    return Mutation(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return dict(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid state file {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"state file root must be an object: {path}")
    return value


def read_string_list(state: dict[str, Any], key: str) -> list[str]:
    value = state.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValidationError(f"state field {key!r} must be a list of non-empty strings")
    return list(value)


def resolve_owned_runtime_path(runtime_root: Path, relative: str) -> Path:
    candidate_path = Path(relative)
    if candidate_path.is_absolute() or ".." in candidate_path.parts:
        raise ValidationError(
            f"state field owned_runtime_files contains an unsafe path: {relative!r}"
        )
    root = runtime_root.resolve()
    candidate = (root / candidate_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValidationError(
            f"state field owned_runtime_files escapes the workflow runtime: {relative!r}"
        ) from error
    if candidate == root:
        raise ValidationError("state field owned_runtime_files cannot target the runtime root")
    return candidate


def deduplicate(mutations: Iterable[Mutation]) -> list[Mutation]:
    result: dict[Path, Mutation] = {}
    order: list[Path] = []
    for mutation in mutations:
        if mutation.path not in result:
            order.append(mutation.path)
        result[mutation.path] = mutation
    return [result[path] for path in order]
