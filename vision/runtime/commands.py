"""Canonical native command surface shared by every platform backend.

One mapping defines Vision's route and lifecycle commands. Platform adapters
render that mapping into Codex skills (``$vision-heavy``) or OpenCode slash
commands (``/heavy``). The commands are entry points only: they activate the
existing shared workflow and call the deterministic lifecycle runtime; they do
not restate route logic or reimplement mutations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .markers import substitute_vision_home


CODEX_SKILL_PREFIX = "vision-"
COMMAND_MARKER_PREFIX = "vision-command:"
_COMMAND_MARKER = re.compile(
    r"^<!-- vision-command: ([a-z0-9-]+) -->$", re.MULTILINE
)


@dataclass(frozen=True)
class CommandSpec:
    """One native command, independent of the target client."""

    name: str
    kind: str  # "route" | "lifecycle"
    title: str
    description: str
    route: str | None = None
    route_doc: str | None = None
    guide: str | None = None
    action: str | None = None
    takes_arguments: bool = False

    @property
    def codex_skill(self) -> str:
        return f"{CODEX_SKILL_PREFIX}{self.name}"


VISION_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        name="light",
        kind="route",
        title="Vision Light Route",
        description="Work directly with the Vision Light route: no subagents, minimal context.",
        route="Light",
    ),
    CommandSpec(
        name="medium",
        kind="route",
        title="Vision Medium Route",
        description="Start the Vision Medium route and complete the task with read-only support workers.",
        route="Medium",
        route_doc="medium_route.md",
    ),
    CommandSpec(
        name="heavy",
        kind="route",
        title="Vision Heavy Route",
        description="Start the Vision Heavy route and complete the task with delegated workers.",
        route="Heavy",
        route_doc="heavy_route.md",
    ),
    CommandSpec(
        name="install",
        kind="lifecycle",
        title="Vision Install",
        description="Install the Vision workflow into the current project using its lifecycle runtime.",
        guide="install.md",
        action="install",
    ),
    CommandSpec(
        name="update",
        kind="lifecycle",
        title="Vision Update",
        description="Update the installed Vision workflow using its lifecycle runtime.",
        guide="update.md",
        action="update",
    ),
    CommandSpec(
        name="config",
        kind="lifecycle",
        title="Vision Config",
        description="Change a Vision orchestrator, Senior Executor, or OpenCode worker-role model.",
        guide="config.md",
        action="config",
        takes_arguments=True,
    ),
    CommandSpec(
        name="remove",
        kind="lifecycle",
        title="Vision Remove",
        description="Remove the installed Vision workflow after confirmation using its lifecycle runtime.",
        guide="remove.md",
        action="remove",
    ),
)

COMMAND_NAMES: tuple[str, ...] = tuple(command.name for command in VISION_COMMANDS)
COMMANDS_BY_NAME: dict[str, CommandSpec] = {
    command.name: command for command in VISION_COMMANDS
}


def command_marker(name: str) -> str:
    return f"<!-- {COMMAND_MARKER_PREFIX} {name} -->"


def command_marker_name(text: str) -> str | None:
    match = _COMMAND_MARKER.search(text)
    return match.group(1) if match is not None else None


def _route_body(spec: CommandSpec, *, platform: str) -> list[str]:
    if spec.route_doc is not None:
        contract = (
            f"Follow the same {spec.route} route contract defined in "
            f"`{{{{VISION_HOME}}}}/{spec.route_doc}`. Read that route document if it "
            "is not already in context."
        )
    else:
        contract = (
            "Light works directly without subagents and with minimal context; do "
            "not enter deployment state unless the task is substantive."
        )
    if platform == "opencode":
        return [
            f"Activate the Vision **{spec.route}** route, then complete the task.",
            "",
            "Task: $ARGUMENTS",
            "",
            f"- Select the {spec.route} route exactly as the shared `AGENTS.md` "
            "route-selection policy defines; do not restate or reimplement route "
            "logic here.",
            f"- {contract}",
            f"- The natural-language form `use {spec.route.lower()} route. <task>` "
            "is equivalent and must enter the same route.",
        ]
    return [
        f"Activate the Vision **{spec.route}** route for the user's request, then "
        "complete it under the shared Vision workflow contract.",
        "",
        "- Treat the task text the user supplied after this command as the request.",
        f"- Select the {spec.route} route exactly as the shared `AGENTS.md` "
        "route-selection policy defines; do not restate or reimplement route logic "
        "here.",
        f"- {contract}",
        f"- The natural-language form `use {spec.route.lower()} route. <task>` is "
        "equivalent and must enter the same route.",
    ]


def _lifecycle_body(spec: CommandSpec, *, platform: str) -> list[str]:
    if spec.action == "config":
        invocation = "config --key <key> --value <value> --json"
        argument_line = (
            "Use the arguments supplied after the command as the key and value."
        )
    else:
        invocation = f"{spec.action} --project <project>"
        argument_line = "Use the current project as `<project>`."
    return [
        "Call Vision's deterministic lifecycle runtime; do not perform the "
        "mutation in this prompt.",
        "",
        "```text",
        f"python3 {{{{VISION_HOME}}}}/runtime/workflow.py {invocation}",
        "```",
        "",
        f"- {argument_line}",
        f"- Then read and follow `{{{{VISION_HOME}}}}/operate/{spec.guide}` and "
        "report the command's result without describing a failed or rolled-back "
        "change as successful.",
    ]


def _body(spec: CommandSpec, *, platform: str) -> list[str]:
    if spec.kind == "route":
        return _route_body(spec, platform=platform)
    return _lifecycle_body(spec, platform=platform)


def render_codex_skill(spec: CommandSpec, *, home_display: str) -> str:
    """Render one command as a Codex skill ``SKILL.md``."""

    lines = [
        "---",
        f"name: {spec.codex_skill}",
        f"description: {spec.description}",
        "---",
        "",
        f"# {spec.title}",
        "",
        command_marker(spec.name),
        "",
        *_body(spec, platform="codex"),
        "",
    ]
    return substitute_vision_home("\n".join(lines), home_display=home_display)


def render_codex_interface(spec: CommandSpec) -> str:
    """Render the Codex skill interface descriptor for one command."""

    return (
        "interface:\n"
        f'  display_name: "{spec.title}"\n'
        f'  short_description: "{spec.description}"\n'
        f'  default_prompt: "Use ${spec.codex_skill} to {spec.description[0].lower()}{spec.description[1:]}"\n'
    )


def render_opencode_command(spec: CommandSpec, *, home_display: str) -> str:
    """Render one command as an OpenCode ``commands/<name>.md`` file."""

    lines = [
        "---",
        f"description: {spec.description}",
        "---",
        "",
        command_marker(spec.name),
        "",
        *_body(spec, platform="opencode"),
        "",
    ]
    return substitute_vision_home("\n".join(lines), home_display=home_display)


__all__ = [
    "CODEX_SKILL_PREFIX",
    "COMMANDS_BY_NAME",
    "COMMAND_NAMES",
    "CommandSpec",
    "VISION_COMMANDS",
    "command_marker",
    "command_marker_name",
    "render_codex_interface",
    "render_codex_skill",
    "render_opencode_command",
]
