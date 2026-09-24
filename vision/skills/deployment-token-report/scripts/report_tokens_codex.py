#!/usr/bin/env python3
"""Compile deployment-scoped Codex rollout token usage without reading prose."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


DEPLOYMENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MARKER_PREFIX = "vision-deployment-start:"


class ReportError(ValueError):
    """Raised when rollout evidence cannot support a trustworthy report."""


@dataclass(frozen=True)
class Session:
    session_id: str
    path: Path
    timestamp: datetime
    parent_id: str | None
    task_name: str | None
    role: str | None


@dataclass
class Usage:
    rollouts: int = 0
    cached_input_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.rollouts += other.rollouts
        self.cached_input_tokens += other.cached_input_tokens
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class Row:
    agent: str
    quantity: int
    usage: Usage
    first_activity: datetime


def parse_time(raw: str, *, field: str) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise ReportError(f"{field} must be a non-empty RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReportError(f"invalid {field}: {raw!r}") from error
    if parsed.tzinfo is None:
        raise ReportError(f"{field} must include a timezone: {raw!r}")
    return parsed.astimezone(timezone.utc)


def iter_jsonl(path: Path, warnings: list[str]) -> Iterator[dict[str, Any]]:
    try:
        with path.open("rb") as stream:
            line_number = 0
            while True:
                line = stream.readline()
                if not line:
                    break
                line_number += 1
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    if not line.endswith(b"\n"):
                        warnings.append(
                            f"ignored incomplete trailing record in {path.name}"
                        )
                        break
                    raise ReportError(
                        f"malformed JSONL record {path.name}:{line_number}"
                    ) from error
                if not isinstance(value, dict):
                    raise ReportError(
                        f"JSONL record is not an object: {path.name}:{line_number}"
                    )
                yield value
    except OSError as error:
        raise ReportError(f"cannot read rollout {path}: {error}") from error


def session_from_path(path: Path, warnings: list[str]) -> Session | None:
    for index, record in enumerate(iter_jsonl(path, warnings)):
        if record.get("type") != "session_meta":
            if index >= 127:
                break
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ReportError(f"invalid session metadata in {path.name}")
        session_id = payload.get("id") or payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ReportError(f"session metadata has no ID in {path.name}")
        timestamp = parse_time(
            payload.get("timestamp") or record.get("timestamp"),
            field=f"session timestamp in {path.name}",
        )
        parent_id = task_name = role = None
        source = payload.get("source")
        if isinstance(source, dict):
            subagent = source.get("subagent")
            if isinstance(subagent, dict):
                spawn = subagent.get("thread_spawn")
                if isinstance(spawn, dict):
                    parent_id = _optional_string(spawn.get("parent_thread_id"))
                    task_name = _optional_string(spawn.get("agent_path"))
                    role = _optional_string(spawn.get("agent_role"))
        return Session(session_id, path, timestamp, parent_id, task_name, role)
    return None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def build_index(sessions_root: Path, warnings: list[str]) -> dict[str, Session]:
    if not sessions_root.is_dir():
        raise ReportError(f"Codex sessions directory is missing: {sessions_root}")
    result: dict[str, Session] = {}
    for path in sessions_root.rglob("*.jsonl"):
        if not path.is_file():
            continue
        session = session_from_path(path, warnings)
        if session is None:
            continue
        previous = result.get(session.session_id)
        if previous is not None and previous.path != session.path:
            raise ReportError(f"duplicate rollout session ID: {session.session_id}")
        result[session.session_id] = session
    return result


def message_texts(
    record: dict[str, Any], *, roles: frozenset[str]
) -> Iterable[str]:
    if record.get("type") != "response_item":
        return ()
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ()
    if payload.get("type") != "message" or payload.get("role") not in roles:
        return ()
    content = payload.get("content")
    if not isinstance(content, list):
        return ()
    return tuple(
        item.get("text")
        for item in content
        if isinstance(item, dict)
        and item.get("type") in {"input_text", "output_text"}
        and isinstance(item.get("text"), str)
    )


def user_texts(record: dict[str, Any]) -> Iterable[str]:
    return message_texts(record, roles=frozenset({"user"}))


def record_time(record: dict[str, Any], *, path: Path) -> datetime:
    return parse_time(record.get("timestamp"), field=f"record timestamp in {path.name}")


def find_boundary(
    root: Session, deployment_id: str, warnings: list[str]
) -> datetime:
    marker = f"{MARKER_PREFIX} {deployment_id}"
    marker_pattern = re.compile(re.escape(marker) + r"(?![a-z0-9_-])")
    marker_times: list[datetime] = []
    for record in iter_jsonl(root.path, warnings):
        texts = message_texts(record, roles=frozenset({"assistant"}))
        if any(marker_pattern.search(text) for text in texts):
            marker_times.append(record_time(record, path=root.path))
    if not marker_times:
        raise ReportError(
            f"deployment marker {marker!r} was not found in the main-agent rollout"
        )
    marker_time = min(marker_times)

    candidates: list[datetime] = []
    for record in iter_jsonl(root.path, warnings):
        timestamp = record_time(record, path=root.path)
        if timestamp > marker_time:
            continue
        if tuple(user_texts(record)):
            candidates.append(timestamp)
    if not candidates:
        raise ReportError("no main-agent user turn precedes the deployment marker")
    return max(candidates)


def descendants(root_id: str, index: dict[str, Session]) -> list[Session]:
    by_parent: dict[str, list[Session]] = defaultdict(list)
    for session in index.values():
        if session.parent_id is not None:
            by_parent[session.parent_id].append(session)
    result: list[Session] = []
    queue = deque([root_id])
    seen = {root_id}
    while queue:
        parent = queue.popleft()
        for child in sorted(
            by_parent.get(parent, ()), key=lambda item: (item.timestamp, item.session_id)
        ):
            if child.session_id in seen:
                raise ReportError(f"cycle in session ancestry at {child.session_id}")
            seen.add(child.session_id)
            result.append(child)
            queue.append(child.session_id)
    return result


def _token_integer(value: Any, *, field: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReportError(f"invalid {field} in {path.name}")
    return value


def usage_from_record(record: dict[str, Any], path: Path) -> Usage | None:
    if record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = _token_integer(
        usage.get("input_tokens"), field="input token count", path=path
    )
    output_tokens = _token_integer(
        usage.get("output_tokens"), field="output token count", path=path
    )
    cached = usage.get("cached_input_tokens")
    if cached is None:
        details = usage.get("input_tokens_details")
        if isinstance(details, dict):
            cached = details.get("cached_tokens")
    cached_tokens = _token_integer(
        cached, field="cached-input token count", path=path
    )
    if cached_tokens > input_tokens:
        raise ReportError(f"cached-input tokens exceed input tokens in {path.name}")
    return Usage(1, cached_tokens, input_tokens, output_tokens)


def aggregate_session(
    session: Session,
    start: datetime,
    end: datetime,
    warnings: list[str],
) -> Usage:
    total = Usage()
    for record in iter_jsonl(session.path, warnings):
        usage = usage_from_record(record, session.path)
        if usage is None:
            continue
        timestamp = record_time(record, path=session.path)
        if start <= timestamp <= end:
            total.add(usage)
    return total


def compile_rows(
    root: Session,
    index: dict[str, Session],
    start: datetime,
    end: datetime,
    warnings: list[str],
) -> list[Row]:
    grouped_usage: dict[str, Usage] = defaultdict(Usage)
    grouped_tasks: dict[str, set[str]] = defaultdict(set)
    first_activity: dict[str, datetime] = {}

    for child in descendants(root.session_id, index):
        usage = aggregate_session(child, start, end, warnings)
        spawned_in_window = start <= child.timestamp <= end
        if not spawned_in_window and usage.rollouts == 0:
            continue
        role = child.role or "unclassified"
        task_name = child.task_name or f"session:{child.session_id}"
        grouped_usage[role].add(usage)
        grouped_tasks[role].add(task_name)
        activity = max(start, child.timestamp)
        first_activity[role] = min(first_activity.get(role, activity), activity)

    rows = [
        Row(role, len(grouped_tasks[role]), usage, first_activity[role])
        for role, usage in grouped_usage.items()
    ]
    rows.sort(key=lambda row: (row.first_activity, row.agent))
    rows.append(Row("main agent", 1, aggregate_session(root, start, end, warnings), start))
    return rows


def markdown(rows: list[Row]) -> str:
    lines = [
        "| Agent | Quantity | Rollouts | Cached input | Input | Output |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {} | {:,} | {:,} | {:,} | {:,} | {:,} |".format(
                row.agent,
                row.quantity,
                row.usage.rollouts,
                row.usage.cached_input_tokens,
                row.usage.input_tokens,
                row.usage.output_tokens,
            )
        )
    return "\n".join(lines)


def json_output(
    deployment_id: str,
    root: Session,
    start: datetime,
    end: datetime,
    rows: list[Row],
    warnings: list[str],
) -> str:
    payload = {
        "schema_version": 1,
        "deployment_id": deployment_id,
        "root_session_id": root.session_id,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": [
            {
                "agent": row.agent,
                "quantity": row.quantity,
                "rollouts": row.usage.rollouts,
                "cached_input_tokens": row.usage.cached_input_tokens,
                "input_tokens": row.usage.input_tokens,
                "output_tokens": row.usage.output_tokens,
            }
            for row in rows
        ],
        "warnings": sorted(set(warnings)),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--deployment-id", required=True)
    result.add_argument(
        "--sessions-root",
        type=Path,
        default=Path.home() / ".codex" / "sessions",
    )
    result.add_argument("--caller-session-id")
    result.add_argument("--root-session-id")
    result.add_argument("--start-time")
    result.add_argument("--end-time")
    result.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not DEPLOYMENT_ID.fullmatch(args.deployment_id):
            raise ReportError(
                f"invalid deployment ID {args.deployment_id!r}; expected "
                "[a-z0-9][a-z0-9_-]{0,63}"
            )
        if (args.root_session_id is None) != (args.start_time is None):
            raise ReportError("--root-session-id and --start-time must be used together")
        warnings: list[str] = []
        index = build_index(args.sessions_root.expanduser().resolve(), warnings)
        end = (
            parse_time(args.end_time, field="end time")
            if args.end_time
            else datetime.now(timezone.utc)
        )
        if args.root_session_id:
            root = index.get(args.root_session_id)
            if root is None:
                raise ReportError(f"root session was not found: {args.root_session_id}")
            start = parse_time(args.start_time, field="start time")
        else:
            caller_id = args.caller_session_id or os.environ.get("CODEX_THREAD_ID")
            if not caller_id:
                raise ReportError(
                    "CODEX_THREAD_ID is unavailable; pass --caller-session-id"
                )
            caller = index.get(caller_id)
            if caller is None:
                raise ReportError(f"caller session was not found: {caller_id}")
            if caller.parent_id is None or caller.role != "archivist":
                raise ReportError("the caller is not a spawned Archivist session")
            root = index.get(caller.parent_id)
            if root is None:
                raise ReportError(
                    f"parent main-agent session is missing: {caller.parent_id}"
                )
            start = find_boundary(root, args.deployment_id, warnings)
        if start > end:
            raise ReportError("deployment start is after report cutoff")
        rows = compile_rows(root, index, start, end, warnings)
        if args.format == "json":
            print(json_output(args.deployment_id, root, start, end, rows, warnings))
        else:
            print(markdown(rows))
            for warning in sorted(set(warnings)):
                print(f"Warning: {warning}", file=sys.stderr)
        return 0
    except ReportError as error:
        print(f"deployment-token-report: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
