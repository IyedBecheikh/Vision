"""Canonical, platform-neutral worker role definitions.

The canonical instruction body for each role lives in ``workers/<role>.md``.
Platform adapters render that one body into Codex TOML or OpenCode Markdown so
the two clients cannot drift apart. Legacy packages that predate the canonical
store fall back to reading the packaged Codex TOML definitions.
"""

from __future__ import annotations

from pathlib import Path

from ._toml import tomllib
from .errors import ValidationError
from .platforms.base import WorkerSpec


WORKER_ROLES: tuple[str, ...] = (
    "explorer",
    "investigator",
    "default_executor",
    "senior_executor",
    "tester",
    "archivist",
)

_FRONT_MATTER_KEYS = ("role", "description", "model_target", "reasoning_effort", "sandbox_mode")
_MODEL_TARGETS = {"luna", "sol"}


def _parse_front_matter(path: Path) -> WorkerSpec:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValidationError(f"canonical worker is missing front matter: {path}")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValidationError(f"canonical worker front matter is unterminated: {path}") from error

    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValidationError(f"canonical worker field is malformed: {line!r}")
        fields[key.strip()] = value.strip()

    for key in _FRONT_MATTER_KEYS:
        if key not in fields:
            raise ValidationError(f"canonical worker {path.name} is missing {key!r}")
    role = fields["role"]
    if role != path.stem:
        raise ValidationError(f"canonical worker role does not match its file name: {path}")
    if fields["model_target"] not in _MODEL_TARGETS:
        raise ValidationError(f"canonical worker has an unsupported model target: {path}")

    body = "\n".join(lines[closing + 1 :]).strip("\n")
    if not body:
        raise ValidationError(f"canonical worker instruction body is empty: {path}")
    return WorkerSpec(
        role=role,
        description=fields["description"],
        instructions=body,
        model_target=fields["model_target"],
        reasoning_effort=fields["reasoning_effort"],
        sandbox_mode=fields["sandbox_mode"],
    )


def _parse_legacy_toml(path: Path) -> WorkerSpec:
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"invalid legacy worker TOML {path.name}: {error}") from error
    role = path.stem
    model = str(data.get("model", "gpt-6-luna"))
    model_target = "sol" if model.endswith("sol") else "luna"
    return WorkerSpec(
        role=role,
        description=str(data.get("description", "")).strip(),
        instructions=str(data.get("developer_instructions", "")).strip("\n"),
        model_target=model_target,
        reasoning_effort=str(data.get("model_reasoning_effort", "")),
        sandbox_mode=str(data.get("sandbox_mode", "workspace-write")),
    )


def load_worker_specs(
    workers_dir: Path | None,
    toml_dir: Path | None,
) -> dict[str, WorkerSpec]:
    """Load canonical specs, preferring the Markdown store over legacy TOML."""

    specs: dict[str, WorkerSpec] = {}
    if workers_dir is not None and workers_dir.is_dir():
        for path in sorted(workers_dir.glob("*.md")):
            if path.is_file():
                spec = _parse_front_matter(path)
                specs[spec.role] = spec
    if specs:
        return specs
    if toml_dir is not None and toml_dir.is_dir():
        for path in sorted(toml_dir.glob("*.toml")):
            if path.is_file():
                spec = _parse_legacy_toml(path)
                specs[spec.role] = spec
    return specs


def render_codex_worker(spec: WorkerSpec, *, model: str) -> str:
    """Render one canonical role as a Codex worker TOML definition."""

    lines = [
        f"# vision-worker: {spec.role}",
        f'name = "{spec.role}"',
    ]
    if spec.description:
        lines.append(f'description = "{spec.description}"')
    lines.append("")
    lines.append(f'model = "{model}"')
    if spec.reasoning_effort:
        lines.append(f'model_reasoning_effort = "{spec.reasoning_effort}"')
    lines.append(f'sandbox_mode = "{spec.sandbox_mode}"')
    lines.append("")
    lines.append('developer_instructions = """')
    lines.append(spec.instructions)
    lines.append('"""')
    lines.append("")
    return "\n".join(lines)
