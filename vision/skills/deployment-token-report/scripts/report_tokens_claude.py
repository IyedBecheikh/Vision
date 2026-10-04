#!/usr/bin/env python3
"""Compile deployment-scoped Claude Code session token usage.

Reads Claude Code transcript JSONL records beneath ``~/.claude/projects`` (or
pre-exported transcripts supplied with ``--export-file`` / ``--export-dir``) and
reports per-agent rollout and token totals. Subagent transcripts are resolved
from ``subagents/`` directories or from sidechain records carrying an
``agentId``; only metadata and token-count fields are read.
"""

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
    """Raised when transcript evidence cannot support a trustworthy report."""


@dataclass(frozen=True)
class Session:
    session_id: str
    path: Path
    timestamp: datetime
    parent_id: str | None
    role: str | None
    filter_agent: str | None = None


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


def parse_time(raw: Any, *, field: str) -> datetime:
    if isinstance(raw, bool):
        raise ReportError(f"{field} must be a timestamp")
    if isinstance(raw, (int, float)):
        seconds = float(raw)
        if seconds > 1e12:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if not isinstance(raw, str) or not raw:
        raise ReportError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReportError(f"invalid {field}: {raw!r}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
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
        raise ReportError(f"cannot read transcript {path}: {error}") from error


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _record_agent(record: dict[str, Any]) -> str | None:
    for key in ("subagentType", "agentId", "agent"):
        value = _optional_string(record.get(key))
        if value:
            return value
    message = record.get("message")
    if isinstance(message, dict):
        return _optional_string(message.get("agent"))
    return None


def _record_time(record: dict[str, Any]) -> datetime | None:
    value = record.get("timestamp")
    if value is None:
        return None
    return parse_time(value, field="record timestamp")


def _subagents_parent(path: Path) -> str | None:
    parts = path.parts
    if "subagents" in parts:
        index = parts.index("subagents")
        if index > 0:
            return parts[index - 1]
    return None


def sessions_from_path(path: Path, warnings: list[str]) -> list[Session]:
    records = list(iter_jsonl(path, warnings))
    if not records:
        return []
    parent_from_path = _subagents_parent(path)
    session_id = parent_from_path or path.stem
    for record in records:
        candidate = (
            _optional_string(record.get("sessionId"))
            or _optional_string(record.get("session_id"))
        )
        if candidate:
            session_id = candidate
            break
    timestamp: datetime | None = None
    role: str | None = None
    parent_id: str | None = parent_from_path
    for record in records:
        if timestamp is None:
            timestamp = _record_time(record)
        if role is None:
            role = _record_agent(record)
        if parent_id is None:
            parent_id = (
                _optional_string(record.get("parentSessionId"))
                or _optional_string(record.get("parent_session_id"))
            )
    if timestamp is None:
        raise ReportError(f"transcript has no timestamp records: {path.name}")
    if parent_from_path is not None:
        role = role or path.stem
        session_id = parent_from_path if session_id == parent_from_path else f"{parent_from_path}:{session_id}"
    sessions = [Session(session_id, path, timestamp, parent_id, role)]

    sidechain_agents = sorted(
        {
            _optional_string(record.get("agentId"))
            for record in records
            if record.get("isSidechain") and _optional_string(record.get("agentId"))
        }
    )
    for agent in sidechain_agents:
        sessions.append(
            Session(
                f"{session_id}:{agent}",
                path,
                timestamp,
                None if parent_from_path else session_id,
                agent,
                filter_agent=agent,
            )
        )
    return sessions


def build_index(paths: Iterable[Path], warnings: list[str]) -> dict[str, Session]:
    result: dict[str, Session] = {}
    for path in sorted(paths):
        if not path.is_file():
            continue
        for session in sessions_from_path(path, warnings):
            previous = result.get(session.session_id)
            if previous is not None and previous.path != session.path:
                raise ReportError(f"duplicate transcript session ID: {session.session_id}")
            result[session.session_id] = session
    return result


def _content_texts(message: dict[str, Any]) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            texts.append(item["text"])
    return texts


def _message_record(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    return message if isinstance(message, dict) else None


def _belongs(record: dict[str, Any], session: Session) -> bool:
    if session.filter_agent is None:
        return not record.get("isSidechain")
    return _optional_string(record.get("agentId")) == session.filter_agent


def find_boundary(root: Session, deployment_id: str, warnings: list[str]) -> datetime:
    marker = f"{MARKER_PREFIX} {deployment_id}"
    pattern = re.compile(re.escape(marker) + r"(?![a-z0-9_-])")
    marker_times: list[datetime] = []
    user_times: list[datetime] = []
    for record in iter_jsonl(root.path, warnings):
        if not _belongs(record, root):
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        timestamp = _record_time(record)
        if timestamp is None:
            continue
        if message.get("role") == "assistant" and any(
            pattern.search(text) for text in _content_texts(message)
        ):
            marker_times.append(timestamp)
        if message.get("role") == "user":
            user_times.append(timestamp)
    if not marker_times:
        raise ReportError(
            f"deployment marker {marker!r} was not found in the main-agent transcript"
        )
    marker_time = min(marker_times)
    candidates = [timestamp for timestamp in user_times if timestamp <= marker_time]
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
        for child in sorted(by_parent.get(parent, ()), key=lambda item: (item.timestamp, item.session_id)):
            if child.session_id in seen:
                raise ReportError(f"cycle in transcript ancestry at {child.session_id}")
            seen.add(child.session_id)
            result.append(child)
            queue.append(child.session_id)
    return result


def _token(value: Any, *, field: str, path: Path) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReportError(f"invalid {field} in {path.name}")
    return value


def usage_from_record(record: dict[str, Any], path: Path) -> Usage | None:
    message = _message_record(record)
    if message is None:
        return None
    tokens = message.get("usage")
    if not isinstance(tokens, dict):
        return None
    input_tokens = _token(
        tokens.get("input_tokens", tokens.get("input")), field="input token count", path=path
    )
    output_tokens = _token(
        tokens.get("output_tokens", tokens.get("output")), field="output token count", path=path
    )
    cache_read = tokens.get("cache_read_input_tokens")
    cache_creation = _token(
        tokens.get("cache_creation_input_tokens"), field="cache-creation token count", path=path
    )
    if cache_read is None:
        cache = tokens.get("cache")
        if isinstance(cache, dict):
            cache_read = cache.get("read", cache.get("read_tokens"))
    cached = _token(cache_read, field="cached-input token count", path=path)
    total_input = input_tokens + cache_creation + cached
    if cached > total_input:
        raise ReportError(f"cached-input tokens exceed input tokens in {path.name}")
    return Usage(1, cached, total_input, output_tokens)


def aggregate_session(
    session: Session, start: datetime, end: datetime, warnings: list[str]
) -> Usage:
    total = Usage()
    for record in iter_jsonl(session.path, warnings):
        if not _belongs(record, session):
            continue
        timestamp = _record_time(record)
        if timestamp is None or timestamp < start or timestamp > end:
            continue
        usage = usage_from_record(record, session.path)
        if usage is not None:
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
    grouped_quantity: dict[str, int] = defaultdict(int)
    first_activity: dict[str, datetime] = {}

    for child in descendants(root.session_id, index):
        usage = aggregate_session(child, start, end, warnings)
        if usage.rollouts == 0 and child.timestamp < start:
            continue
        role = child.role or "unclassified"
        grouped_usage[role].add(usage)
        grouped_quantity[role] += 1
        activity = max(start, child.timestamp)
        first_activity[role] = min(first_activity.get(role, activity), activity)

    rows = [
        Row(role, grouped_quantity[role], grouped_usage[role], first_activity[role])
        for role in grouped_usage
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
        "platform": "claude",
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
        "--projects-root",
        type=Path,
        default=Path.home() / ".claude" / "projects",
    )
    result.add_argument("--caller-session-id")
    result.add_argument("--root-session-id")
    result.add_argument("--start-time")
    result.add_argument("--end-time")
    result.add_argument("--export-file", type=Path)
    result.add_argument("--export-dir", type=Path)
    result.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return result


def _transcript_paths(args: argparse.ArgumentParser) -> list[Path]:
    paths: list[Path] = []
    if args.export_file is not None:
        paths.append(args.export_file.expanduser())
    if args.export_dir is not None:
        paths.extend(sorted(args.export_dir.expanduser().rglob("*.jsonl")))
    if not paths:
        root = args.projects_root.expanduser()
        if not root.is_dir():
            raise ReportError(f"Claude Code projects directory is missing: {root}")
        paths.extend(sorted(root.rglob("*.jsonl")))
    return paths


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
        index = build_index(_transcript_paths(args), warnings)
        if not index:
            raise ReportError("no Claude Code transcripts were found")
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
            caller_id = args.caller_session_id or os.environ.get("CLAUDE_SESSION_ID")
            if caller_id:
                caller = index.get(caller_id)
                if caller is None:
                    raise ReportError(f"caller session was not found: {caller_id}")
                if caller.parent_id is None:
                    raise ReportError("the caller session is not a spawned subagent session")
                root = index.get(caller.parent_id)
                if root is None:
                    raise ReportError(
                        f"parent main-agent transcript is missing: {caller.parent_id}"
                    )
            else:
                roots = [session for session in index.values() if session.parent_id is None]
                if len(roots) != 1:
                    raise ReportError(
                        "cannot infer the main-agent transcript; pass --root-session-id or "
                        "--caller-session-id"
                    )
                root = roots[0]
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
