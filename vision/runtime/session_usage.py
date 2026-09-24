"""Platform-neutral session usage collection through installed backends.

Each adapter exposes ``collect_session_usage`` by running Vision's shared token
report entry point with the matching ``--platform`` backend and decoding the
JSON rows into :class:`SessionUsage` records. Keeping the report scripts as the
single source of truth avoids duplicating parsing logic in the runtime.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .errors import PlatformError
from .platforms.base import SessionUsage


def _script_path(skills_dir: Path) -> Path:
    candidate = skills_dir / "deployment-token-report" / "scripts" / "report_tokens.py"
    if candidate.is_file():
        return candidate
    packaged = Path(__file__).resolve().parent.parent / "skills" / "deployment-token-report" / "scripts" / "report_tokens.py"
    if packaged.is_file():
        return packaged
    raise PlatformError(
        f"the deployment-token-report backend is not installed: {candidate}"
    )


def _collect(platform: str, skills_dir: Path, options: dict[str, Any]) -> list[SessionUsage]:
    script = _script_path(skills_dir)
    deployment_id = options.get("deployment_id")
    if not deployment_id:
        raise PlatformError("collect_session_usage requires deployment_id")
    command = [
        sys.executable,
        "-B",
        str(script),
        "--platform",
        platform,
        "--deployment-id",
        str(deployment_id),
        "--format",
        "json",
    ]
    mapping = {
        "caller_session_id": "--caller-session-id",
        "root_session_id": "--root-session-id",
        "start_time": "--start-time",
        "end_time": "--end-time",
        "sessions_root": "--sessions-root",
        "opencode_bin": "--opencode-bin",
        "export_file": "--export-file",
        "export_dir": "--export-dir",
    }
    for key, flag in mapping.items():
        value = options.get(key)
        if value is not None:
            command.extend([flag, str(value)])
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as error:
        raise PlatformError(f"cannot run the token report backend: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise PlatformError(f"token report backend failed: {detail or 'unknown error'}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PlatformError(f"token report backend returned invalid JSON: {error}") from error
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise PlatformError("token report backend returned no rows")
    usage: list[SessionUsage] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        usage.append(
            SessionUsage(
                agent=str(row.get("agent", "unclassified")),
                quantity=int(row.get("quantity", 0)),
                rollouts=int(row.get("rollouts", 0)),
                cached_input_tokens=int(row.get("cached_input_tokens", 0)),
                input_tokens=int(row.get("input_tokens", 0)),
                output_tokens=int(row.get("output_tokens", 0)),
            )
        )
    return usage


def collect_codex_usage(**options: Any) -> list[SessionUsage]:
    skills_dir = Path(options.pop("skills_dir"))
    return _collect("codex", skills_dir, options)


def collect_opencode_usage(**options: Any) -> list[SessionUsage]:
    skills_dir = Path(options.pop("skills_dir"))
    return _collect("opencode", skills_dir, options)
