#!/usr/bin/env python3
"""Compile deployment-scoped OpenCode session token usage.

Uses OpenCode's exposed session interfaces (``session list`` and ``export``)
instead of undocumented filesystem internals. For deterministic tests and
offline review, pre-exported session JSON can be supplied with ``--export-file``
or ``--export-dir``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEPLOYMENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MARKER_PREFIX = "vision-deployment-start:"


class ReportError(ValueError):
    """Raised when session evidence cannot support a trustworthy report."""


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


@dataclass
class Session:
    session_id: str
    parent_id: str | None
    created: datetime | None
    agent: str | None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def role(self) -> str:
        if self.agent:
            return self.agent
        for message in self.messages:
            info = message.get("info")
            if isinstance(info, dict) and info.get("role") == "assistant":
                value = info.get("agent") or info.get("mode")
                if isinstance(value, str) and value:
                    return value
        return "unclassified"


def _parse_time(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, bool):
        raise ReportError(f"{field_name} must be a timestamp")
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e12:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ReportError(f"invalid {field_name}: {value!r}") from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ReportError(f"{field_name} is missing")


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _session_from_export(export: dict[str, Any], *, source: str) -> Session:
    info = export.get("info") if isinstance(export.get("info"), dict) else export.get("session")
    if not isinstance(info, dict):
        raise ReportError(f"session export has no info object: {source}")
    session_id = _optional_string(info.get("id")) or _optional_string(info.get("sessionID"))
    if not session_id:
        raise ReportError(f"session export has no ID: {source}")
    parent = (
        _optional_string(info.get("parentID"))
        or _optional_string(info.get("parent_id"))
        or _optional_string(info.get("parent"))
    )
    created: datetime | None = None
    time_value = info.get("time")
    if isinstance(time_value, dict) and "created" in time_value:
        created = _parse_time(time_value["created"], field_name=f"session created in {source}")
    agent = _optional_string(info.get("agent"))
    messages = export.get("messages")
    if not isinstance(messages, list):
        messages = []
    return Session(session_id, parent, created, agent, [m for m in messages if isinstance(m, dict)])


class _Provider:
    """Resolve OpenCode sessions through exports or the native CLI."""

    def __init__(
        self,
        *,
        bin_path: str,
        export_file: Path | None,
        export_dir: Path | None,
        timeout: int = 120,
    ) -> None:
        self.bin_path = bin_path
        self.timeout = timeout
        self._cache: dict[str, Session] = {}
        self._order: list[str] = []
        if export_file is not None:
            self._load_paths([export_file])
        if export_dir is not None:
            self._load_paths(sorted(export_dir.rglob("*.json")))

    def _load_paths(self, paths: Iterable[Path]) -> None:
        for path in paths:
            try:
                export = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ReportError(f"cannot read session export {path}: {error}") from error
            if not isinstance(export, dict):
                raise ReportError(f"session export is not an object: {path}")
            session = _session_from_export(export, source=str(path))
            if session.session_id in self._cache:
                raise ReportError(f"duplicate exported session ID: {session.session_id}")
            self._cache[session.session_id] = session
            self._order.append(session.session_id)

    @property
    def offline(self) -> bool:
        return bool(self._cache)

    def _run(self, arguments: list[str]) -> Any:
        command = [self.bin_path, *arguments]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ReportError(f"cannot run {self.bin_path!r}: {error}") from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ReportError(f"opencode command failed: {detail or 'unknown error'}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ReportError(f"opencode returned non-JSON output: {error}") from error

    def session_ids(self) -> list[str]:
        if self.offline:
            return list(self._order)
        records = self._run(["session", "list", "--format", "json"])
        if isinstance(records, dict):
            records = records.get("sessions") or records.get("data") or []
        if not isinstance(records, list):
            raise ReportError("opencode session list did not return a list")
        ids: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            session_id = _optional_string(record.get("id")) or _optional_string(record.get("sessionID"))
            if session_id:
                ids.append(session_id)
        return ids

    def session(self, session_id: str) -> Session:
        if session_id in self._cache:
            return self._cache[session_id]
        export = self._run(["export", session_id])
        if not isinstance(export, dict):
            raise ReportError(f"opencode export did not return an object: {session_id}")
        session = _session_from_export(export, source=session_id)
        self._cache[session.session_id] = session
        return session

    def index(self) -> dict[str, Session]:
        return {session_id: self.session(session_id) for session_id in self.session_ids()}


def _message_time(message: dict[str, Any]) -> datetime | None:
    info = message.get("info")
    if not isinstance(info, dict):
        return None
    time_value = info.get("time")
    if isinstance(time_value, dict) and "created" in time_value:
        return _parse_time(time_value["created"], field_name="message created")
    if "created" in info:
        return _parse_time(info["created"], field_name="message created")
    return None


def _message_texts(message: dict[str, Any], *, roles: frozenset[str]) -> list[str]:
    info = message.get("info")
    if not isinstance(info, dict) or info.get("role") not in roles:
        return []
    parts = message.get("parts")
    if not isinstance(parts, list):
        return []
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return texts


def _boundary(root: Session, deployment_id: str) -> datetime:
    marker = f"{MARKER_PREFIX} {deployment_id}"
    pattern = re.compile(re.escape(marker) + r"(?![a-z0-9_-])")
    marker_times: list[datetime] = []
    user_times: list[datetime] = []
    for message in root.messages:
        timestamp = _message_time(message)
        if timestamp is None:
            continue
        for text in _message_texts(message, roles=frozenset({"assistant"})):
            if pattern.search(text):
                marker_times.append(timestamp)
        if _message_texts(message, roles=frozenset({"user"})):
            user_times.append(timestamp)
    if not marker_times:
        raise ReportError(
            f"deployment marker {marker!r} was not found in the main-agent session"
        )
    marker_time = min(marker_times)
    candidates = [timestamp for timestamp in user_times if timestamp <= marker_time]
    if not candidates:
        raise ReportError("no main-agent user turn precedes the deployment marker")
    return max(candidates)


def _usage_from_message(message: dict[str, Any], session_id: str) -> Usage | None:
    info = message.get("info")
    if not isinstance(info, dict) or info.get("role") != "assistant":
        return None
    tokens = info.get("tokens")
    if not isinstance(tokens, dict):
        tokens = info.get("usage")
    if not isinstance(tokens, dict):
        return None
    input_tokens = _token(tokens.get("input") if "input" in tokens else tokens.get("input_tokens"))
    output_tokens = _token(tokens.get("output") if "output" in tokens else tokens.get("output_tokens"))
    cached = _cached_tokens(tokens)
    if input_tokens is None or output_tokens is None:
        return None
    if cached is None:
        cached = 0
    if cached > input_tokens:
        raise ReportError(f"cached-input tokens exceed input tokens in {session_id}")
    return Usage(1, cached, input_tokens, output_tokens)


def _token(value: Any) -> int | None:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReportError("token counts must be non-negative integers")
    return value


def _cached_tokens(tokens: dict[str, Any]) -> int | None:
    for key in ("cached_input_tokens", "cachedInputTokens", "cache_read_input_tokens"):
        if key in tokens:
            return _token(tokens[key]) or 0
    cache = tokens.get("cache")
    if isinstance(cache, dict):
        for key in ("read", "read_tokens", "cachedInputTokens"):
            if key in cache:
                return _token(cache[key]) or 0
    return None


def _descendants(root_id: str, index: dict[str, Session]) -> list[Session]:
    by_parent: dict[str, list[Session]] = {}
    for session in index.values():
        if session.parent_id is not None:
            by_parent.setdefault(session.parent_id, []).append(session)
    result: list[Session] = []
    seen = {root_id}
    queue = [root_id]
    while queue:
        parent = queue.pop(0)
        for child in sorted(
            by_parent.get(parent, ()),
            key=lambda item: (item.created or datetime.min.replace(tzinfo=timezone.utc), item.session_id),
        ):
            if child.session_id in seen:
                raise ReportError(f"cycle in session ancestry at {child.session_id}")
            seen.add(child.session_id)
            result.append(child)
            queue.append(child.session_id)
    return result


def _compile_rows(
    root: Session,
    index: dict[str, Session],
    start: datetime,
    end: datetime,
) -> list[Row]:
    grouped_usage: dict[str, Usage] = {}
    grouped_quantity: dict[str, int] = {}
    first_activity: dict[str, datetime] = {}

    def consider(role: str, usage: Usage, activity: datetime) -> None:
        grouped_usage.setdefault(role, Usage()).add(usage)
        grouped_quantity[role] = grouped_quantity.get(role, 0) + 1
        previous = first_activity.get(role)
        first_activity[role] = activity if previous is None else min(previous, activity)

    for child in _descendants(root.session_id, index):
        usage = Usage()
        for message in child.messages:
            timestamp = _message_time(message)
            if timestamp is None or timestamp < start or timestamp > end:
                continue
            partial = _usage_from_message(message, child.session_id)
            if partial is not None:
                usage.add(partial)
        spawned = child.created is not None and start <= child.created <= end
        if not spawned and usage.rollouts == 0:
            continue
        activity = max(start, child.created) if child.created else start
        consider(child.role(), usage, activity)

    rows = [
        Row(role, grouped_quantity[role], usage, first_activity[role])
        for role, usage in grouped_usage.items()
    ]
    rows.sort(key=lambda row: (row.first_activity, row.agent))
    main_usage = Usage()
    for message in root.messages:
        timestamp = _message_time(message)
        if timestamp is None or timestamp < start or timestamp > end:
            continue
        partial = _usage_from_message(message, root.session_id)
        if partial is not None:
            main_usage.add(partial)
    rows.append(Row("main agent", 1, main_usage, start))
    return rows


def _markdown(rows: list[Row]) -> str:
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


def _json_output(
    deployment_id: str,
    root: Session,
    start: datetime,
    end: datetime,
    rows: list[Row],
) -> str:
    payload = {
        "schema_version": 1,
        "platform": "opencode",
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
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--deployment-id", required=True)
    result.add_argument("--format", choices=("markdown", "json"), default="markdown")
    result.add_argument("--caller-session-id")
    result.add_argument("--root-session-id")
    result.add_argument("--start-time")
    result.add_argument("--end-time")
    result.add_argument("--opencode-bin", default="opencode")
    result.add_argument("--export-file", type=Path)
    result.add_argument("--export-dir", type=Path)
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
        provider = _Provider(
            bin_path=args.opencode_bin,
            export_file=args.export_file,
            export_dir=args.export_dir,
        )
        index = provider.index()
        if not index:
            raise ReportError("no OpenCode sessions were found")
        end = (
            _parse_time(args.end_time, field_name="end time")
            if args.end_time
            else datetime.now(timezone.utc)
        )
        if args.root_session_id:
            root = index.get(args.root_session_id)
            if root is None:
                raise ReportError(f"root session was not found: {args.root_session_id}")
            start = _parse_time(args.start_time, field_name="start time")
        else:
            caller_id = args.caller_session_id or os.environ.get("OPENCODE_SESSION_ID")
            if caller_id:
                caller = index.get(caller_id)
                if caller is None:
                    raise ReportError(f"caller session was not found: {caller_id}")
                if caller.parent_id is None:
                    raise ReportError("the caller session is not a spawned subagent session")
                root = index.get(caller.parent_id)
                if root is None:
                    raise ReportError(f"parent main-agent session is missing: {caller.parent_id}")
            else:
                roots = [session for session in index.values() if session.parent_id is None]
                if len(roots) != 1:
                    raise ReportError(
                        "cannot infer the main-agent session; pass --root-session-id or "
                        "--caller-session-id"
                    )
                root = roots[0]
            start = _boundary(root, args.deployment_id)
        if start > end:
            raise ReportError("deployment start is after report cutoff")
        rows = _compile_rows(root, index, start, end)
        if args.format == "json":
            print(_json_output(args.deployment_id, root, start, end, rows))
        else:
            print(_markdown(rows))
        return 0
    except ReportError as error:
        print(f"deployment-token-report: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
