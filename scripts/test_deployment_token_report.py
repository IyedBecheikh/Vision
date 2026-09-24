"""Behavioral tests for the deployment-token-report skill."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "vision"
    / "skills"
    / "deployment-token-report"
    / "scripts"
    / "report_tokens.py"
)


def metadata(
    session_id: str,
    timestamp: str,
    *,
    parent: str | None = None,
    task: str | None = None,
    role: str | None = None,
    guardian: bool = False,
) -> dict[str, object]:
    source: object = "cli"
    thread_source = "user"
    if guardian:
        source = {"subagent": {"other": "guardian"}}
        thread_source = "subagent"
    elif parent is not None:
        source = {
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": parent,
                    "depth": 1,
                    "agent_path": task,
                    "agent_nickname": "fixture",
                    "agent_role": role,
                }
            }
        }
        thread_source = "subagent"
    return {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "session_id": session_id,
            "timestamp": timestamp,
            "source": source,
            "thread_source": thread_source,
        },
    }


def user_message(timestamp: str, text: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def assistant_message(timestamp: str, text: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        },
    }


def usage(
    timestamp: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    *,
    api_shape: bool = False,
) -> dict[str, object]:
    last: dict[str, object] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if api_shape:
        last["input_tokens_details"] = {"cached_tokens": cached_tokens}
    else:
        last["cached_input_tokens"] = cached_tokens
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"last_token_usage": last},
        },
    }


class DeploymentTokenReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.sessions = Path(self.temporary.name) / "sessions" / "2026" / "08" / "23"
        self.sessions.mkdir(parents=True)
        self.root_id = "root-session"
        self.explorer_id = "explorer-session"
        self.closure_id = "closure"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_session(
        self,
        session_id: str,
        records: list[dict[str, object]],
        *,
        incomplete_tail: bool = False,
    ) -> None:
        path = self.sessions / f"rollout-2026-08-23T10-00-00-{session_id}.jsonl"
        rendered = "".join(json.dumps(record) + "\n" for record in records)
        if incomplete_tail:
            rendered += '{"timestamp":'
        path.write_text(rendered, encoding="utf-8")

    def build_fixture(self) -> None:
        self.write_session(
            self.root_id,
            [
                metadata(self.root_id, "2026-08-23T09:00:00Z"),
                user_message("2026-08-23T09:00:01Z", "older request"),
                usage("2026-08-23T09:59:59Z", 999, 900, 99),
                user_message("2026-08-23T10:00:00Z", "deployment request"),
                assistant_message(
                    "2026-08-23T10:00:20Z",
                    "<!-- vision-deployment-start: major_task -->\nStarting.",
                ),
                usage("2026-08-23T10:01:00Z", 100, 60, 20),
                usage("2026-08-23T10:05:00Z", 200, 150, 30),
            ],
        )
        self.write_session(
            self.explorer_id,
            [
                metadata(
                    self.explorer_id,
                    "2026-08-23T10:00:30Z",
                    parent=self.root_id,
                    task="/root/context",
                    role="explorer",
                ),
                assistant_message(
                    "2026-08-23T10:00:31Z",
                    "Project context is ready.",
                ),
                usage("2026-08-23T10:01:30Z", 50, 40, 10),
            ],
            incomplete_tail=True,
        )
        self.write_session(
            "executor-one",
            [
                metadata(
                    "executor-one",
                    "2026-08-23T10:02:00Z",
                    parent=self.root_id,
                    task="/root/implementation_a",
                    role="default_executor",
                ),
                usage("2026-08-23T10:02:30Z", 75, 60, 15),
            ],
        )
        self.write_session(
            "executor-two",
            [
                metadata(
                    "executor-two",
                    "2026-08-23T10:03:00Z",
                    parent=self.root_id,
                    task="/root/implementation_b",
                    role="default_executor",
                ),
                usage("2026-08-23T10:03:30Z", 25, 10, 5, api_shape=True),
            ],
        )
        self.write_session(
            "tester-nested",
            [
                metadata(
                    "tester-nested",
                    "2026-08-23T10:03:40Z",
                    parent="executor-one",
                    task="/root/implementation_a/verify",
                    role="tester",
                ),
                usage("2026-08-23T10:04:00Z", 30, 20, 8),
            ],
        )
        self.write_session(
            self.closure_id,
            [
                metadata(
                    self.closure_id,
                    "2026-08-23T10:04:30Z",
                    parent=self.root_id,
                    task="/root/archivist_major_task",
                    role="archivist",
                ),
                usage("2026-08-23T10:05:30Z", 10, 5, 2),
            ],
        )
        self.write_session(
            "guardian",
            [
                metadata(
                    "guardian",
                    "2026-08-23T10:02:00Z",
                    guardian=True,
                ),
                usage("2026-08-23T10:02:30Z", 5000, 5000, 5000),
            ],
        )

    def run_report(
        self, *extra: str, deployment_id: str = "major_task"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--deployment-id",
                deployment_id,
                "--sessions-root",
                str(self.sessions.parents[2]),
                "--caller-session-id",
                self.closure_id,
                "--end-time",
                "2026-08-23T10:06:00Z",
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_compiles_scoped_six_column_report(self) -> None:
        self.build_fixture()
        completed = self.run_report("--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(
            [row["agent"] for row in report["rows"]],
            [
                "explorer",
                "default_executor",
                "tester",
                "archivist",
                "main agent",
            ],
        )
        by_agent = {row["agent"]: row for row in report["rows"]}
        self.assertEqual(
            by_agent["default_executor"],
            {
                "agent": "default_executor",
                "quantity": 2,
                "rollouts": 2,
                "cached_input_tokens": 70,
                "input_tokens": 100,
                "output_tokens": 20,
            },
        )
        self.assertEqual(by_agent["main agent"]["rollouts"], 2)
        self.assertEqual(by_agent["main agent"]["input_tokens"], 300)
        self.assertEqual(by_agent["main agent"]["cached_input_tokens"], 210)
        self.assertEqual(by_agent["main agent"]["output_tokens"], 50)
        self.assertTrue(report["warnings"])
        self.assertNotIn("guardian", by_agent)

        markdown = self.run_report("--format", "markdown")
        self.assertEqual(markdown.returncode, 0, markdown.stderr)
        lines = markdown.stdout.splitlines()
        self.assertEqual(
            lines[0],
            "| Agent | Quantity | Rollouts | Cached input | Input | Output |",
        )
        self.assertTrue(all(line.count("|") == 7 for line in lines))

    def test_missing_marker_fails_without_guessing(self) -> None:
        self.build_fixture()
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--deployment-id",
                "different_task",
                "--sessions-root",
                str(self.sessions.parents[2]),
                "--caller-session-id",
                self.closure_id,
                "--end-time",
                "2026-08-23T10:06:00Z",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("was not found", completed.stderr)
        self.assertEqual(completed.stdout, "")

    def test_invalid_deployment_id_reports_constraint(self) -> None:
        for invalid_id in (
            "<deployment_id>",
            "<!-- vision-deployment-start: major_task -->",
            "Major-Task",
            "a" * 65,
        ):
            with self.subTest(deployment_id=invalid_id):
                completed = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), "--deployment-id", invalid_id],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn(repr(invalid_id), completed.stderr)
                self.assertIn("[a-z0-9][a-z0-9_-]{0,63}", completed.stderr)
                self.assertEqual(completed.stdout, "")

    def test_repeated_marker_in_main_rollout_is_not_ambiguous(self) -> None:
        self.build_fixture()
        path = self.sessions / "rollout-2026-08-23T10-00-00-root-session.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    assistant_message(
                        "2026-08-23T10:00:32Z",
                        "Confirmed `vision-deployment-start: major_task`.",
                    )
                )
                + "\n"
            )
        completed = self.run_report("--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_marker_does_not_match_a_longer_deployment_id(self) -> None:
        self.build_fixture()
        path = self.sessions / "rollout-2026-08-23T10-00-00-root-session.jsonl"
        text = path.read_text(encoding="utf-8").replace(
            "vision-deployment-start: major_task",
            "vision-deployment-start: major_task_extra",
        )
        path.write_text(text, encoding="utf-8")
        completed = self.run_report()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("was not found", completed.stderr)

    def test_hyphenated_deployment_id_matches_exact_marker(self) -> None:
        self.build_fixture()
        deployment_id = "2026-09-18-unified-chat"
        path = self.sessions / "rollout-2026-08-23T10-00-00-root-session.jsonl"
        text = path.read_text(encoding="utf-8").replace(
            "vision-deployment-start: major_task",
            f"vision-deployment-start: {deployment_id}",
        )
        path.write_text(text, encoding="utf-8")

        completed = self.run_report("--format", "json", deployment_id=deployment_id)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["deployment_id"], deployment_id)

        path.write_text(text.replace(deployment_id, deployment_id + "-extra"), encoding="utf-8")
        longer_marker = self.run_report(deployment_id=deployment_id)
        self.assertEqual(longer_marker.returncode, 2)
        self.assertIn("was not found", longer_marker.stderr)

    def test_marker_in_child_only_is_not_a_boundary(self) -> None:
        self.build_fixture()
        root = self.sessions / "rollout-2026-08-23T10-00-00-root-session.jsonl"
        root.write_text(
            root.read_text(encoding="utf-8").replace(
                "vision-deployment-start: major_task",
                "removed-deployment-boundary",
            ),
            encoding="utf-8",
        )
        explorer = self.sessions / (
            "rollout-2026-08-23T10-00-00-explorer-session.jsonl"
        )
        explorer.write_text(
            explorer.read_text(encoding="utf-8").replace(
                "Project context is ready.",
                "vision-deployment-start: major_task",
            ),
            encoding="utf-8",
        )

        completed = self.run_report()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("main-agent rollout", completed.stderr)

    def test_non_archivist_child_cannot_run_the_closure_owned_report(self) -> None:
        self.build_fixture()
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--deployment-id",
                "major_task",
                "--sessions-root",
                str(self.sessions.parents[2]),
                "--caller-session-id",
                self.explorer_id,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("not a spawned Archivist", completed.stderr)

    def test_direct_root_mode_supports_deterministic_diagnostics(self) -> None:
        self.build_fixture()
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--deployment-id",
                "major_task",
                "--sessions-root",
                str(self.sessions.parents[2]),
                "--root-session-id",
                self.root_id,
                "--start-time",
                "2026-08-23T10:00:00Z",
                "--end-time",
                "2026-08-23T10:06:00Z",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["root_session_id"], self.root_id)


class OpenCodeTokenReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.exports = Path(self.temporary.name) / "exports"
        self.exports.mkdir(parents=True)
        self.root_id = "root-session"
        self.explorer_id = "explorer-session"
        self.closure_id = "archivist-closure"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_export(
        self,
        session_id: str,
        messages: list[dict[str, object]],
        *,
        parent: str | None = None,
        agent: str | None = None,
        created: int = 1755000000000,
    ) -> None:
        info: dict[str, object] = {"id": session_id, "time": {"created": created}}
        if parent is not None:
            info["parentID"] = parent
        if agent is not None:
            info["agent"] = agent
        payload = {"info": info, "messages": messages}
        (self.exports / f"{session_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def build_fixture(self) -> None:
        self.write_export(
            self.root_id,
            [
                {
                    "info": {"role": "user", "time": {"created": 1755000000000}},
                    "parts": [{"type": "text", "text": "deployment request"}],
                },
                {
                    "info": {"role": "assistant", "time": {"created": 1755000010000}},
                    "parts": [
                        {
                            "type": "text",
                            "text": "<!-- vision-deployment-start: major_task -->\nStarting.",
                        }
                    ],
                },
                {
                    "info": {
                        "role": "assistant",
                        "time": {"created": 1755000020000},
                        "tokens": {
                            "input": 300,
                            "output": 50,
                            "cache": {"read": 210, "write": 0},
                        },
                    },
                    "parts": [{"type": "text", "text": "working"}],
                },
            ],
        )
        self.write_export(
            self.explorer_id,
            [
                {
                    "info": {
                        "role": "assistant",
                        "time": {"created": 1755000030000},
                        "tokens": {"input": 50, "output": 10, "cache": {"read": 40}},
                    },
                    "parts": [{"type": "text", "text": "context map"}],
                }
            ],
            parent=self.root_id,
            agent="explorer",
            created=1755000015000,
        )
        self.write_export(
            self.closure_id,
            [
                {
                    "info": {
                        "role": "assistant",
                        "time": {"created": 1755000050000},
                        "tokens": {"input": 10, "output": 2, "cache": {"read": 5}},
                    },
                    "parts": [{"type": "text", "text": "closure"}],
                }
            ],
            parent=self.root_id,
            agent="archivist",
            created=1755000040000,
        )

    def run_report(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--platform",
                "opencode",
                "--deployment-id",
                "major_task",
                "--export-dir",
                str(self.exports),
                "--caller-session-id",
                self.closure_id,
                "--end-time",
                "2026-08-23T10:06:00Z",
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_compiles_opencode_six_column_report(self) -> None:
        self.build_fixture()
        completed = self.run_report("--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["platform"], "opencode")
        by_agent = {row["agent"]: row for row in report["rows"]}
        self.assertEqual(by_agent["explorer"]["input_tokens"], 50)
        self.assertEqual(by_agent["explorer"]["cached_input_tokens"], 40)
        self.assertEqual(by_agent["explorer"]["quantity"], 1)
        self.assertEqual(by_agent["archivist"]["output_tokens"], 2)
        self.assertEqual(by_agent["main agent"]["input_tokens"], 300)
        self.assertEqual(by_agent["main agent"]["cached_input_tokens"], 210)

        markdown = self.run_report("--format", "markdown")
        self.assertEqual(markdown.returncode, 0, markdown.stderr)
        lines = markdown.stdout.splitlines()
        self.assertEqual(
            lines[0],
            "| Agent | Quantity | Rollouts | Cached input | Input | Output |",
        )
        self.assertTrue(all(line.count("|") == 7 for line in lines))

    def test_missing_marker_fails_without_guessing(self) -> None:
        self.build_fixture()
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--platform",
                "opencode",
                "--deployment-id",
                "different_task",
                "--export-dir",
                str(self.exports),
                "--caller-session-id",
                self.closure_id,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("was not found", completed.stderr)
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main()
