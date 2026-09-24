"""Regression tests for the lifecycle runtime."""

from __future__ import annotations

import json
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "vision"
PACKAGE_VERSION = (PACKAGE / "operate" / "VERSION").read_text(encoding="utf-8").strip()


def next_patch_version(version: str) -> str:
    major, minor, patch = version.split("+", 1)[0].split("-", 1)[0].split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


NEXT_PACKAGE_VERSION = next_patch_version(PACKAGE_VERSION)


def legacy_project_entry(*, personalization: str = "", local: str = "") -> str:
    personalization_body = f"{personalization.rstrip()}\n" if personalization else ""
    local_body = f"{local.rstrip()}\n" if local else ""
    return (
        "<!-- vision-id: IyedBecheikh/vision -->\n"
        "<!-- vision-managed-start -->\n"
        "# Legacy Workflow Policy\n"
        "<!-- vision-managed-end -->\n\n"
        "<!-- vision-project-personalization-start -->\n"
        f"{personalization_body}"
        "<!-- vision-project-personalization-end -->\n\n"
        "<!-- vision-project-local-instructions-start -->\n"
        f"{local_body}"
        "<!-- vision-project-local-instructions-end -->\n"
    )

sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "runtime"))
sys.path.insert(0, str(ROOT / "scripts"))

import workflow as workflow_cli
from package_release import (
    ReleaseError as PackageReleaseError,
    _verify_member_names,
    build_zip,
    verify_archive,
)

from runtime.platform_settings import (
    patch_codex_settings,
    patch_orchestrator_model,
    patch_worker_model,
    remove_workflow_owned_settings,
)
from runtime.backup import append_backup_mutations
from runtime.errors import TransactionError, ValidationError
from runtime.lifecycle import (
    PackageLayout,
    ProjectPaths,
    RuntimePaths,
    plan_bootstrap,
    plan_project_install,
    plan_project_only_update,
    plan_remove,
    plan_update,
)
from runtime.markers import (
    PROJECT_LOCAL,
    USER_MANAGED,
)
from runtime.plan import OperationPlan, read_string_list, resolve_owned_runtime_path
from runtime.release import (
    ReleaseSelection,
    parse_semver,
    select_releases,
    summarize_release_notes,
)
from runtime.transaction import Mutation, apply


class MarkerTests(unittest.TestCase):
    def test_user_command_contract_exposes_only_supported_lifecycle_prompts(self) -> None:
        instructions = (PACKAGE / "operate" / "user_AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("vision --check-update", instructions)
        self.assertIn("vision --remove", instructions)
        self.assertNotIn("vision --personal", instructions)
        self.assertNotIn("vision --disable", instructions)
        self.assertNotIn("vision --enable", instructions)
        self.assertFalse((PACKAGE / "AGENTS.md").exists())

    def test_operational_policies_are_compact_and_knowledge_aware(self) -> None:
        policies = {
            name: (PACKAGE / name).read_text(encoding="utf-8")
            for name in ("operate/user_AGENTS.md", "medium_route.md", "heavy_route.md")
        }
        for name, limit in (
            ("operate/user_AGENTS.md", 180),
            ("medium_route.md", 155),
            ("heavy_route.md", 245),
        ):
            self.assertLess(len(policies[name].splitlines()), limit, name)

        agents_policy = policies["operate/user_AGENTS.md"]
        medium = policies["medium_route.md"]
        heavy = policies["heavy_route.md"]
        self.assertIn("directly read the complete current", " ".join(agents_policy.split()))
        self.assertIn("two Explorers a bounded", " ".join(agents_policy.split()))
        self.assertIn("start two independent", agents_policy)
        self.assertIn("start three independent", agents_policy)
        self.assertIn("Use Light when none is selected", agents_policy)
        self.assertIn("Never repeat\nit later in the session", agents_policy)
        self.assertIn("Missing or unreadable required documents", agents_policy)
        for document in (
            "project_progress.md",
            "project_diary.md",
            "latest_session_work.md",
        ):
            self.assertIn(document, agents_policy)
            self.assertIn(document, medium)
            self.assertIn(document, heavy)

        self.assertIn("Medium does not delegate production or verification", medium)
        self.assertIn("| Explorer |", medium)
        self.assertIn("| Investigator |", medium)
        self.assertIn("| Archivist |", medium)
        self.assertIn("Limit Medium workers to Explorer, Investigator, and Archivist", medium)
        self.assertIn("start exactly three", medium)
        self.assertIn("start exactly two", medium)
        self.assertIn("one shared Exploration ID", medium)
        self.assertIn("one shared Problem ID", medium)
        self.assertIn("distinct Task IDs", medium)
        self.assertIn("rather than voting", medium)
        self.assertIn("retry or replace that lane", medium)
        self.assertIn("## Context Routing After Intake", medium)
        self.assertIn("deployment-boundary rule in `AGENTS.md`", medium)

        self.assertIn("central knowledge director", heavy)
        self.assertIn("do not become a production Executor", " ".join(heavy.split()))
        self.assertNotIn("send_message", heavy)
        self.assertIn("smallest complete decision-ready report", " ".join(heavy.split()))
        self.assertIn("directly to the main", " ".join(heavy.split()))
        self.assertIn("Wait for all three reports", " ".join(heavy.split()))
        self.assertIn("at most one Senior Executor", heavy)
        self.assertIn("Explorer for bounded context discovery", heavy)
        self.assertIn("Investigator for evidence-backed solution search", heavy)
        self.assertIn("start exactly three", heavy)
        self.assertIn("start exactly two", heavy)
        self.assertIn("one shared Exploration ID", heavy)
        self.assertIn("distinct Task IDs", heavy)
        self.assertIn("one shared Problem ID", heavy)
        self.assertIn("rather than voting", heavy)
        self.assertIn("retry or replace only that lane", " ".join(heavy.split()))
        self.assertIn("defining gates, assigning execution", heavy)
        self.assertIn("owning Executor for repair", heavy)
        self.assertIn("same\n  Tester for recheck", heavy)
        self.assertIn("non-overlapping ownership", heavy)
        self.assertIn("Do not poll workers", heavy)
        self.assertIn("deployment-boundary rule in `AGENTS.md`", heavy)

        explorer = (PACKAGE / "agents" / "explorer.toml").read_text(encoding="utf-8")
        investigator = (PACKAGE / "agents" / "investigator.toml").read_text(encoding="utf-8")
        executor = (PACKAGE / "agents" / "default_executor.toml").read_text(encoding="utf-8")
        senior = (PACKAGE / "agents" / "senior_executor.toml").read_text(encoding="utf-8")
        tester = (PACKAGE / "agents" / "tester.toml").read_text(encoding="utf-8")
        archivist = (PACKAGE / "agents" / "archivist.toml").read_text(encoding="utf-8")
        for role in (explorer, investigator, executor, senior, tester):
            self.assertIn("Task ID", role)
            self.assertIn("complete capsule structure", " ".join(role.split()))
        self.assertIn("what exists and where", explorer)
        self.assertIn("one other Explorer", explorer)
        self.assertIn("Exploration ID in every report", " ".join(explorer.split()))
        self.assertIn('sandbox_mode = "read-only"', explorer)
        self.assertIn("plausible fault", investigator)
        self.assertIn("two other Investigators", investigator)
        self.assertIn("Problem ID in every report", " ".join(investigator.split()))
        self.assertIn("Work independently", investigator)
        self.assertIn('sandbox_mode = "read-only"', investigator)
        for role in (explorer, investigator, executor, senior, tester):
            role_flat = " ".join(role.split())
            self.assertIn("directly to the main", role_flat)
            self.assertIn("final response", role_flat)
            self.assertIn("Do not attempt worker-to-worker messaging", role_flat)
            self.assertNotIn("Report recipient", role)
            self.assertNotIn("send_message", role)
        self.assertIn("do not repair production code", " ".join(tester.split()))
        self.assertIn("ordinary repair", executor)
        self.assertIn("unresolved hard decision", senior)
        self.assertIn('model = "gpt-6-luna"', explorer)
        self.assertIn('model = "gpt-6-luna"', investigator)
        self.assertIn('model = "gpt-6-luna"', executor)
        self.assertIn('model = "gpt-6-sol"', senior)
        self.assertIn('model = "gpt-6-luna"', tester)
        self.assertIn('model = "gpt-6-luna"', archivist)

        handoff = (PACKAGE / "archivist.md").read_text(encoding="utf-8")
        self.assertIn('agent_type="archivist"', handoff)
        self.assertIn('fork_turns="200"', handoff)
        self.assertIn("one reporting owner", handoff)
        self.assertIn("$deployment-token-report", archivist)
        skill = (
            PACKAGE / "skills" / "deployment-token-report" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            skill.count("| Agent | Quantity | Rollouts | Cached input | Input | Output |"),
            1,
        )
        for policy in (agents_policy, medium, heavy, handoff, archivist):
            self.assertNotIn("end this session", policy.lower())

    def test_closure_bootstrap_and_worker_boundaries_remain_explicit(self) -> None:
        skill = (
            PACKAGE / "skills" / "deployment-token-report" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("The required table template is exactly", skill)
        self.assertIn("| --- | ---: | ---: | ---: | ---: | ---: |", skill)
        self.assertIn("Keep the columns exactly as shown", skill)
        self.assertIn("Use the supplied deployment ID unchanged", skill)
        self.assertIn("assistant message text there", skill)

        handoff = (PACKAGE / "archivist.md").read_text(encoding="utf-8")
        archivist = (PACKAGE / "agents" / "archivist.toml").read_text(
            encoding="utf-8"
        )
        self.assertIn("Keep those files outside Archivist's write", handoff)
        self.assertIn("one reporting owner", handoff)
        self.assertIn("Do not\nedit those files during a deployment", archivist)
        self.assertIn("Preserve\nits exact six-column table", archivist)
        for document in ("project_progress.md", "latest_session_work.md"):
            self.assertIn(document, archivist)
            template = (PACKAGE / "project_docs" / document).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("updates this document", template)

        bootstrap = (PACKAGE / "operate" / "bootstrap.md").read_text(
            encoding="utf-8"
        )
        install = (PACKAGE / "operate" / "install.md").read_text(
            encoding="utf-8"
        )
        for document in (
            "project_structure.md",
            "project_overview.md",
            "project_core_tech.md",
        ):
            self.assertIn(document, bootstrap)
            self.assertIn(document, install)

        executor = (PACKAGE / "agents" / "default_executor.toml").read_text(
            encoding="utf-8"
        )
        senior = (PACKAGE / "agents" / "senior_executor.toml").read_text(
            encoding="utf-8"
        )
        tester = (PACKAGE / "agents" / "tester.toml").read_text(
            encoding="utf-8"
        )
        for role in (executor, senior):
            self.assertIn("Implementation Context + Ownership", role)
            self.assertIn("Implementation Task + Goal", role)
            self.assertIn("Main-Agent Implementation Guidance", role)
        for part in (
            "Verification Context",
            "Verification Goal",
            "Main-Agent Verification Guidance",
        ):
            self.assertIn(part, tester)
        self.assertIn("Never weaken assertions", tester)
        self.assertIn("Leave repair and re-verification decisions with the main", tester)

    def test_native_project_agents_is_preserved_even_with_legacy_marker_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text(PROJECT_LOCAL.start, encoding="utf-8")
            plan_bootstrap(
                PackageLayout.resolve(PACKAGE),
                RuntimePaths(root / "home"),
                ProjectPaths(project),
            ).apply()
            self.assertEqual((project / "AGENTS.md").read_text(), PROJECT_LOCAL.start)

    def test_package_requires_exact_user_managed_region(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "vision"
            shutil.copytree(
                PACKAGE,
                root,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            path = root / "operate" / "user_AGENTS.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(USER_MANAGED.start, "", 1), encoding="utf-8"
            )
            with self.assertRaises(ValidationError):
                PackageLayout.resolve(root)

    def test_package_requires_complete_builtin_worker_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "vision"
            shutil.copytree(
                PACKAGE,
                root,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            (root / "agents" / "tester.toml").unlink()
            (root / "agents" / "archivist.toml").unlink()
            with self.assertRaisesRegex(
                ValidationError, "package worker set is incomplete"
            ):
                PackageLayout.resolve(root)

    def test_package_requires_builtin_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "vision"
            shutil.copytree(
                PACKAGE,
                root,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            shutil.rmtree(root / "skills" / "deployment-token-report")
            with self.assertRaisesRegex(ValidationError, "package skill set"):
                PackageLayout.resolve(root)

    def test_update_help_does_not_publish_local_source_option(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(PACKAGE / "runtime" / "workflow.py"), "update", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("--source", completed.stdout)
        self.assertNotIn("--apply", completed.stdout)

    def test_check_update_command_is_available(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(PACKAGE / "runtime" / "workflow.py"), "check-update", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_remove_help_hides_internal_confirmation_flag(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(PACKAGE / "runtime" / "workflow.py"), "remove", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("--confirm", completed.stdout)


class SafetyTests(unittest.TestCase):
    def test_owned_runtime_manifest_is_confined_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / "runtime"
            with self.assertRaises(ValidationError):
                resolve_owned_runtime_path(runtime_root, "../../outside.txt")
            with self.assertRaises(ValidationError):
                resolve_owned_runtime_path(runtime_root, "/tmp/outside.txt")
        with self.assertRaises(ValidationError):
            read_string_list({"owned_runtime_files": None}, "owned_runtime_files")

    def test_backup_skips_missing_optional_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            mutations: list[Mutation] = []
            append_backup_mutations(
                mutations,
                root / "backup",
                RuntimePaths(root / "home"),
                ProjectPaths(project),
            )
            self.assertEqual(mutations, [])


class PlatformSettingsTests(unittest.TestCase):
    def test_toml_patch_preserves_unrelated_content(self) -> None:
        original = 'model = "custom"\n\n[agents]\nenabled = false\nother = 7\n'
        rendered = patch_codex_settings(original)
        self.assertIn('model = "custom"', rendered)
        self.assertIn("other = 7", rendered)
        self.assertIn("[agents]", rendered)
        self.assertNotIn("max_concurrent_threads_per_session", rendered)
        self.assertIn("[features]", rendered)
        self.assertIn("multi_agent = true", rendered)
        self.assertEqual(
            tomllib.loads(rendered)["features"]["multi_agent_v2"],
            {
                "enabled": True,
                "min_wait_timeout_ms": 300000,
                "default_wait_timeout_ms": 300000,
                "max_wait_timeout_ms": 1800000,
            },
        )
        self.assertNotIn("hide_spawn_agent_metadata", rendered)

    def test_toml_patch_migrates_legacy_multi_agent_settings(self) -> None:
        original = (
            "[features.multi_agent_v2]\n"
            "enabled = true\n"
            "min_wait_timeout_ms = 1000\n"
            "default_wait_timeout_ms = 2000\n"
            "max_wait_timeout_ms = 3000\n"
            "max_concurrent_threads_per_session = 8\n"
            "hide_spawn_agent_metadata = false\n"
            'keep_legacy = "keep"\n'
        )
        rendered = patch_codex_settings(original)
        self.assertIn("[features.multi_agent_v2]", rendered)
        self.assertIn('keep_legacy = "keep"', rendered)
        self.assertNotIn("hide_spawn_agent_metadata", rendered)
        self.assertIn("[agents]", rendered)
        self.assertNotIn("max_concurrent_threads_per_session", rendered)
        self.assertIn("[features]", rendered)
        self.assertIn("multi_agent = true", rendered)
        self.assertEqual(
            tomllib.loads(rendered)["features"]["multi_agent_v2"],
            {
                "enabled": True,
                "min_wait_timeout_ms": 300000,
                "default_wait_timeout_ms": 300000,
                "max_wait_timeout_ms": 1800000,
                "keep_legacy": "keep",
            },
        )
        self.assertEqual(patch_codex_settings(rendered), rendered)

    def test_toml_patch_removes_legacy_agents_alias(self) -> None:
        original = (
            "[agents]\n"
            "max_concurrent_threads_per_session = 20\n"
            "max_threads = 8\n"
            "max_depth = 1\n"
            "job_max_runtime_seconds = 1800\n"
        )
        rendered = patch_codex_settings(original)
        self.assertNotIn("max_threads", rendered)
        self.assertIn("max_depth = 1", rendered)
        self.assertIn("job_max_runtime_seconds = 1800", rendered)
        self.assertNotIn("max_concurrent_threads_per_session", rendered)

    def test_toml_patch_replaces_owned_v2_gate(self) -> None:
        rendered = patch_codex_settings(
            "[features.multi_agent_v2]\nenabled = false\n"
        )
        self.assertIn("[features.multi_agent_v2]", rendered)
        self.assertNotIn("enabled = false", rendered)
        self.assertTrue(tomllib.loads(rendered)["features"]["multi_agent_v2"]["enabled"])
        self.assertIn("[agents]", rendered)
        self.assertIn("[features]", rendered)

    def test_toml_remove_preserves_unrelated_content(self) -> None:
        original = (
            'model = "custom"\n\n'
            "[agents]\n"
            "enabled = true\n"
            "max_concurrent_threads_per_session = 20\n"
            "keep_agent = true\n\n"
            "[features]\n"
            "multi_agent = true\n"
            'keep_feature = "keep"\n\n'
            "[features.multi_agent_v2]\n"
            "enabled = true\n"
            "min_wait_timeout_ms = 300000\n"
            "default_wait_timeout_ms = 600000\n"
            "max_wait_timeout_ms = 1800000\n"
            'keep_legacy = "keep"\n'
        )
        rendered = remove_workflow_owned_settings(original)
        self.assertIn('model = "custom"', rendered)
        self.assertIn("keep_agent = true", rendered)
        self.assertIn('keep_feature = "keep"', rendered)
        self.assertIn('keep_legacy = "keep"', rendered)
        self.assertNotIn("max_concurrent_threads_per_session", rendered)
        self.assertIn("[agents]", rendered)
        self.assertNotIn("enabled = true", rendered)
        self.assertNotIn("multi_agent = true", rendered)
        self.assertNotIn("min_wait_timeout_ms", rendered)
        self.assertNotIn("default_wait_timeout_ms", rendered)
        self.assertNotIn("max_wait_timeout_ms", rendered)

    def test_fixed_route_and_worker_need_no_settings_rendering(self) -> None:
        heavy = (PACKAGE / "heavy_route.md").read_text(encoding="utf-8")
        default = (PACKAGE / "agents" / "default_executor.toml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("vision-effective-config", heavy)
        self.assertNotIn("Fixed Workflow Settings", heavy)
        self.assertIn('model_reasoning_effort = "max"', default)
        self.assertIn(
            'fork_turns="200"',
            (PACKAGE / "archivist.md").read_text(encoding="utf-8"),
        )


class OrchestratorConfigTests(unittest.TestCase):
    def test_config_sets_top_level_model_and_records_choice(self) -> None:
        original = 'model = "gpt-6-luna"\n\n[agents]\nenabled = false\nkeep = 1\n'
        rendered = patch_orchestrator_model(original, "sol")
        self.assertIn('model = "gpt-6-sol"', rendered)
        self.assertIn("keep = 1", rendered)
        data = tomllib.loads(rendered)
        self.assertEqual(data["model"], "gpt-6-sol")
        self.assertEqual(data["vision"]["orchestrator"], "sol")
        self.assertEqual(data["vision"]["orchestrator_model"], "gpt-6-sol")
        self.assertEqual(patch_orchestrator_model(rendered, "sol"), rendered)

        removed = remove_workflow_owned_settings(rendered)
        self.assertNotIn("[vision]", removed)
        self.assertEqual(tomllib.loads(removed)["model"], "gpt-6-sol")

    def test_config_cli_writes_the_requested_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "codex-home"
            home.mkdir()
            (home / "config.toml").write_text('model = "gpt-6-sol"\n', encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PACKAGE / "runtime" / "workflow.py"),
                    "config",
                    "--key",
                    "orch",
                    "--value",
                    "luna",
                    "--codex-home",
                    str(home),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertTrue(summary["applied"])
            self.assertEqual(summary["details"]["model"], "gpt-6-luna")
            self.assertTrue(summary["details"]["changed"])
            data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "gpt-6-luna")
            self.assertEqual(data["vision"]["orchestrator"], "luna")

    def test_config_senior_sets_worker_model_and_preserves_effort(self) -> None:
        senior = (PACKAGE / "agents" / "senior_executor.toml").read_text(
            encoding="utf-8"
        )
        rendered = patch_worker_model(senior, "luna")
        self.assertIn('model = "gpt-6-luna"', rendered)
        self.assertIn('model_reasoning_effort = "medium"', rendered)
        self.assertEqual(patch_worker_model(rendered, "luna"), rendered)
        parsed = tomllib.loads(rendered)
        self.assertEqual(parsed["model"], "gpt-6-luna")
        self.assertEqual(parsed["model_reasoning_effort"], "medium")

    def test_config_cli_switches_senior_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "codex-home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            (agents / "senior_executor.toml").write_text(
                "# vision-worker: senior_executor\n"
                'name = "senior_executor"\n'
                'model = "gpt-6-sol"\n'
                'model_reasoning_effort = "medium"\n',
                encoding="utf-8",
            )
            (home / "config.toml").write_text("", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(PACKAGE / "runtime" / "workflow.py"),
                    "config",
                    "--key",
                    "senior",
                    "--value",
                    "luna",
                    "--codex-home",
                    str(home),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["details"]["model"], "gpt-6-luna")
            worker = tomllib.loads(
                (agents / "senior_executor.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(worker["model"], "gpt-6-luna")
            self.assertEqual(worker["model_reasoning_effort"], "medium")
            config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["vision"]["senior"], "luna")


class ReleaseTests(unittest.TestCase):
    def _archive_without(self, relative: str) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = Path(temporary.name) / "source.zip"
        target = Path(temporary.name) / "modified.zip"
        build_zip(PACKAGE, source)
        excluded = f"vision/{relative}"
        with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_DEFLATED
        ) as output_archive:
            for member in input_archive.infolist():
                if member.filename == excluded:
                    continue
                output_archive.writestr(member, input_archive.read(member.filename))
        return target

    def test_archive_requires_complete_builtin_worker_set(self) -> None:
        names = ["vision"]
        names.extend(
            f"vision/{path.relative_to(PACKAGE).as_posix()}"
            for path in PACKAGE.rglob("*")
        )
        names = [
            name
            for name in names
            if name
            not in {
                "vision/agents/tester.toml",
                "vision/agents/archivist.toml",
            }
        ]
        with self.assertRaisesRegex(PackageReleaseError, "archive is missing"):
            _verify_member_names(names)

    def test_archive_rejects_unsupported_worker_role(self) -> None:
        names = ["vision"]
        names.extend(
            f"vision/{path.relative_to(PACKAGE).as_posix()}"
            for path in PACKAGE.rglob("*")
        )
        names.append("vision/agents/unexpected.toml")
        with self.assertRaisesRegex(
            PackageReleaseError, "archive contains unsupported worker roles"
        ):
            _verify_member_names(names)

    def test_archive_verification_runs_the_full_package_validator(self) -> None:
        cases = (
            ("operate/user_AGENTS.md", "archive is missing"),
            ("project_docs/project_diary.md", "workflow package validation failed"),
        )
        for missing, error in cases:
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(PackageReleaseError, error):
                    verify_archive(self._archive_without(missing))

    def test_archive_verification_rejects_duplicate_members(self) -> None:
        archive = self._archive_without("not-present")
        with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("vision/operate/VERSION", PACKAGE_VERSION + "\n")
        with self.assertRaisesRegex(PackageReleaseError, "duplicate members"):
            verify_archive(archive)

    def test_update_rejects_older_package_before_delegation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "codex-home" / "vision"
            runtime.mkdir(parents=True)
            (runtime / "VERSION").write_text("1.1.4\n", encoding="utf-8")
            incoming = root / "incoming"
            incoming.mkdir()
            project = root / "project"
            project.mkdir()
            for version, expected_error in (("1.1.3", "incoming version is older"),):
                with self.subTest(version=version):
                    (incoming / "VERSION").write_text(version + "\n", encoding="utf-8")
                    output = io.StringIO()
                    argv = [
                        "workflow.py",
                        "update",
                        "--source",
                        str(incoming),
                        "--codex-home",
                        str(root / "codex-home"),
                        "--project",
                        str(project),
                        "--json",
                    ]
                    with (
                        mock.patch.object(sys, "argv", argv),
                        mock.patch.object(
                            workflow_cli,
                            "_delegate_update",
                            side_effect=AssertionError("delegation must not occur"),
                        ),
                        contextlib.redirect_stdout(output),
                    ):
                        self.assertEqual(workflow_cli.main(), 1)
                    self.assertIn(expected_error, json.loads(output.getvalue())["error"])

    def test_check_update_reports_new_release_notes_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "codex-home"
            runtime = home / "vision"
            runtime.mkdir(parents=True)
            (runtime / "VERSION").write_text("1.1.1\n", encoding="utf-8")
            release = ReleaseSelection(
                "1.2.0",
                parse_semver("1.2.0"),
                "vision-1.2.0.zip",
                "https://example/1.2.0.zip",
                "https://example/SHA256SUMS",
                "## Changes\n- Add release-note summaries.",
                "https://example/releases/1.2.0",
            )
            output = io.StringIO()
            argv = ["workflow.py", "check-update", "--codex-home", str(home), "--json"]
            with (
                mock.patch.object(workflow_cli, "select_releases", return_value=[release]),
                mock.patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(workflow_cli.main(), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["status"], "update available")
            self.assertEqual(summary["updates"][0]["version"], "1.2.0")
            self.assertIn("release-note summaries", summary["summary"])
            self.assertEqual((runtime / "VERSION").read_text(), "1.1.1\n")

    def test_select_releases_keeps_installable_versions_and_notes(self) -> None:
        records = [
            {
                "tag_name": "v1.3.0",
                "draft": False,
                "body": "## Changes\n- Add explicit update summaries.",
                "html_url": "https://github.com/example/releases/1.3.0",
                "assets": [
                    {
                        "name": "vision-1.3.0.zip",
                        "browser_download_url": "https://example/1.3.0.zip",
                    },
                    {"name": "SHA256SUMS", "browser_download_url": "https://example/sums"},
                ],
            },
            {
                "tag_name": "v1.2.0",
                "draft": False,
                "body": "- Older change",
                "assets": [
                    {
                        "name": "vision-1.2.0.zip",
                        "browser_download_url": "https://example/1.2.0.zip",
                    },
                    {"name": "SHA256SUMS", "browser_download_url": "https://example/sums"},
                ],
            },
            {"tag_name": "v1.4.0", "draft": True, "assets": []},
        ]
        with mock.patch("runtime.release._read_json_url", return_value=records):
            releases = select_releases()
        self.assertEqual([release.version_text for release in releases], ["1.3.0", "1.2.0"])
        self.assertIn("explicit update summaries", releases[0].release_notes)

    def test_release_note_summary_strips_markdown_and_limits_length(self) -> None:
        summary = summarize_release_notes(
            "## Changes\n- `check-update` now reports [notes](https://example)."
        )
        self.assertEqual(summary, "Changes check-update now reports notes.")
        self.assertEqual(
            summarize_release_notes("", max_length=10),
            "No release notes were provided.",
        )


class TransactionTests(unittest.TestCase):
    def test_failed_transaction_restores_all_targets(self) -> None:
        from runtime import transaction

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.write_bytes(b"old")
            original_write = transaction._atomic_write
            calls = 0

            def fail_once(path: Path, content: bytes, mode: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected failure")
                original_write(path, content, mode)

            with mock.patch("runtime.transaction._atomic_write", side_effect=fail_once):
                with self.assertRaises(TransactionError):
                    apply([Mutation(first, b"new"), Mutation(second, b"created")])
            self.assertEqual(first.read_bytes(), b"old")
            self.assertFalse(second.exists())


class LifecycleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.runtime = RuntimePaths(self.codex_home)
        self.project = ProjectPaths(self.project_root)
        self.package = PackageLayout.resolve(PACKAGE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bootstrap(self, *, existing_agents: str | None = None) -> OperationPlan:
        if existing_agents is not None:
            self.project.active.write_text(existing_agents, encoding="utf-8")
        plan = plan_bootstrap(self.package, self.runtime, self.project)
        self.assertFalse(self.codex_home.exists())
        plan.apply()
        return plan

    def incoming_package(self, directory: str, version: str | None = None) -> PackageLayout:
        version = version or PACKAGE_VERSION
        incoming_root = self.root / directory / "vision"
        shutil.copytree(
            PACKAGE,
            incoming_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (incoming_root / "operate" / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        user_agents = (incoming_root / "operate" / "user_AGENTS.md").read_text(encoding="utf-8")
        (incoming_root / "operate" / "user_AGENTS.md").write_text(
            user_agents.replace(
                f"vision-version: {PACKAGE_VERSION}",
                f"vision-version: {version}",
            ),
            encoding="utf-8",
        )
        return PackageLayout.resolve(incoming_root)

    def test_bootstrap_imports_existing_agents_and_materializes_runtime(self) -> None:
        plan = self.bootstrap(
            existing_agents="# Existing instructions\nKeep local policy.\n"
        )
        entry = self.project.active.read_text(encoding="utf-8")
        self.assertEqual(
            entry,
            "# Existing instructions\nKeep local policy.\n",
        )
        self.assertTrue((self.runtime.runtime / "runtime" / "workflow.py").is_file())
        self.assertFalse((self.runtime.runtime / "templates" / "AGENTS.md").exists())
        self.assertTrue((self.runtime.agents / "default_executor.toml").is_file())
        self.assertTrue((self.runtime.agents / "senior_executor.toml").is_file())
        self.assertTrue((self.runtime.agents / "explorer.toml").is_file())
        self.assertTrue((self.runtime.agents / "investigator.toml").is_file())
        self.assertTrue((self.runtime.agents / "archivist.toml").is_file())
        self.assertTrue(
            (
                self.runtime.skills
                / "deployment-token-report"
                / "scripts"
                / "report_tokens.py"
            ).is_file()
        )
        self.assertTrue(
            (
                self.runtime.runtime
                / "templates"
                / "skills"
                / "deployment-token-report"
                / "SKILL.md"
            ).is_file()
        )
        self.assertNotIn(
            "max_concurrent_threads_per_session",
            self.runtime.config_toml.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            tomllib.loads(self.runtime.config_toml.read_text(encoding="utf-8"))
            ["features"]["multi_agent_v2"],
            {
                "enabled": True,
                "min_wait_timeout_ms": 300000,
                "default_wait_timeout_ms": 300000,
                "max_wait_timeout_ms": 1800000,
            },
        )
        self.assertEqual(len(plan.agent_actions), 1)
        action = plan.agent_actions[0]
        self.assertEqual(action["role"], "archivist")
        self.assertTrue(action["required"])
        self.assertEqual(set(action["files"]), set(action["framework"]))
        self.assertEqual(
            action["required_context_files"],
            [
                "project_structure.md",
                "project_overview.md",
                "project_core_tech.md",
            ],
        )

        repeated = plan_project_install(self.package, self.project)
        self.assertEqual(len(repeated.agent_actions), 1)
        self.assertTrue(repeated.agent_actions[0]["required"])
        self.assertEqual(
            set(repeated.agent_actions[0]["files"]),
            set(repeated.agent_actions[0]["framework"]),
        )
        self.assertEqual(repeated.agent_actions[0]["created_files"], [])
        self.assertEqual(
            set(repeated.agent_actions[0]["recovery_files"]),
            set(repeated.agent_actions[0]["framework"]),
        )

    def test_bootstrap_requires_review_for_missing_legacy_route(self) -> None:
        self.project.active.write_text(
            legacy_project_entry(
                local="# Project policy\nRead `agent_docs/workflows/heavy_route.md`."
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "missing legacy workflow route"):
            plan_bootstrap(self.package, self.runtime, self.project)

        plan_bootstrap(
            self.package,
            self.runtime,
            self.project,
            legacy_local_instructions="# Project policy\nKeep this rule.\n",
        ).apply()
        self.assertEqual(
            self.project.active.read_text(encoding="utf-8"),
            "# Project policy\nKeep this rule.\n",
        )

    def test_bootstrap_rejects_unowned_skill_collision(self) -> None:
        collision = self.runtime.skills / "deployment-token-report"
        collision.mkdir(parents=True)
        (collision / "SKILL.md").write_text(
            "---\nname: deployment-token-report\ndescription: local\n---\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "unowned skill directory"):
            plan_bootstrap(self.package, self.runtime, self.project)

    def test_bootstrap_cleans_staging_and_keeps_agent_docs_trackable(self) -> None:
        staging = self.project_root / "Vision_Workflow"
        (staging / "nested").mkdir(parents=True)
        (staging / "nested" / "package.txt").write_text("staged", encoding="utf-8")
        (self.project_root / ".gitignore").write_text("# local rules\n", encoding="utf-8")

        self.bootstrap()

        self.assertFalse(staging.exists())
        gitignore = (self.project_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("# local rules\n", gitignore)
        self.assertNotIn("agent_docs/", gitignore)
        self.assertEqual(
            gitignore.splitlines().count(".vision_hidden_resources/"), 1
        )
        self.assertNotIn("AGENTS.md", gitignore)
        self.assertIn("# vision-managed-start", gitignore)
        self.assertIn("# vision-managed-end", gitignore)

        # A repeated project install is idempotent and does not duplicate rules.
        plan_project_install(self.package, self.project).apply()
        repeated = (self.project_root / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("agent_docs/", repeated)
        self.assertEqual(
            repeated.splitlines().count(".vision_hidden_resources/"), 1
        )
        self.assertNotIn("AGENTS.md", repeated)

    def test_remove_restores_project_local_instructions_and_gitignore(self) -> None:
        self.bootstrap(existing_agents="# Original project instructions\nKeep this.\n")
        self.project.docs.mkdir(exist_ok=True)
        preserved_document = self.project.docs / "project_overview.md"
        preserved_document.write_text("Project documentation\n", encoding="utf-8")
        gitignore = self.project_root / ".gitignore"
        gitignore.write_text(
            "# local rule\nlocal-output/\n\n"
            + gitignore.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        plan_remove(self.runtime, self.project).apply()

        self.assertEqual(
            self.project.active.read_text(encoding="utf-8"),
            "# Original project instructions\nKeep this.\n",
        )
        self.assertTrue(preserved_document.is_file())
        remaining_gitignore = gitignore.read_text(encoding="utf-8")
        self.assertIn("# local rule\nlocal-output/\n", remaining_gitignore)
        self.assertNotIn("# vision-managed-start", remaining_gitignore)
        for entry in (
            "agent_docs/",
            ".vision_hidden_resources/",
            "AGENTS.md",
        ):
            self.assertNotIn(entry, remaining_gitignore)

    def test_install_preserves_user_owned_agent_docs_ignore(self) -> None:
        self.project.gitignore.write_text("agent_docs/\n", encoding="utf-8")

        self.bootstrap()

        gitignore = self.project.gitignore.read_text(encoding="utf-8")
        self.assertEqual(gitignore.splitlines().count("agent_docs/"), 1)
        self.assertLess(
            gitignore.splitlines().index("agent_docs/"),
            gitignore.splitlines().index("# vision-managed-start"),
        )

    def test_new_install_preserves_user_owned_legacy_shaped_ignore(self) -> None:
        self.project.gitignore.write_text(
            "agent_docs/\n.vision_hidden_resources/\nAGENTS.md\n",
            encoding="utf-8",
        )

        self.bootstrap()

        gitignore = self.project.gitignore.read_text(encoding="utf-8")
        for entry in (
            "agent_docs/",
            ".vision_hidden_resources/",
            "AGENTS.md",
        ):
            self.assertEqual(gitignore.splitlines().count(entry), 1)
        self.assertNotIn("# vision-managed-start", gitignore)

    def test_install_retires_legacy_unmarked_agent_docs_ignore(self) -> None:
        self.bootstrap()
        self.project.gitignore.write_text(
            "# local\nagent_docs/\n.vision_hidden_resources/\nAGENTS.md\n",
            encoding="utf-8",
        )

        plan_project_install(self.package, self.project).apply()

        gitignore = self.project.gitignore.read_text(encoding="utf-8")
        self.assertIn("# local\n", gitignore)
        self.assertNotIn("agent_docs/", gitignore)
        self.assertIn("# vision-managed-start", gitignore)
        self.assertIn("# vision-managed-end", gitignore)

    def test_remove_restores_project_local_instructions_from_disabled_entry(self) -> None:
        self.bootstrap()
        self.project.disabled.write_text(
            legacy_project_entry(local="# Original project instructions\nKeep this."),
            encoding="utf-8",
        )
        self.assertFalse(self.project.active.exists())
        self.assertTrue(self.project.disabled.exists())

        plan_remove(self.runtime, self.project).apply()

        self.assertEqual(
            self.project.active.read_text(encoding="utf-8"),
            "# Original project instructions\nKeep this.\n",
        )
        self.assertFalse(self.project.disabled.exists())
        self.assertFalse(self.project.workflow_dir.exists())

    def test_unactivated_workers_are_materialized_for_codex(self) -> None:
        self.bootstrap()
        for worker in self.package.worker_names:
            self.assertTrue((self.runtime.agents / f"{worker}.toml").is_file())
            self.assertTrue(
                (self.runtime.runtime / "templates" / "agents" / f"{worker}.toml").is_file()
            )
        state = json.loads((self.runtime.runtime / "install_state.json").read_text())
        self.assertEqual(set(state["owned_workers"]), self.package.worker_names)
        self.assertEqual(set(state["owned_skills"]), self.package.skill_names)

    def test_install_migrates_legacy_personalization_and_local_regions(self) -> None:
        self.project.active.write_text(
            legacy_project_entry(
                personalization="Prefer explicit ports and adapters.",
                local="Local policy.",
            ),
            encoding="utf-8",
        )
        self.bootstrap()
        self.assertEqual(
            self.project.active.read_text(encoding="utf-8"),
            "Prefer explicit ports and adapters.\n\nLocal policy.\n",
        )
        self.assertFalse(self.project.personalization.exists())

    def test_install_preserves_native_project_agents_after_local_edits(self) -> None:
        self.bootstrap(existing_agents="Local policy.\n")
        self.project.active.write_text("Locally revised policy.\n", encoding="utf-8")
        plan_project_install(self.package, self.project).apply()
        self.assertEqual(self.project.active.read_text(), "Locally revised policy.\n")

    def test_update_restores_workers_and_preserves_project_state(self) -> None:
        self.bootstrap(existing_agents="Local policy.\n")
        gitignore = self.project.gitignore
        gitignore.write_text(
            gitignore.read_text(encoding="utf-8").replace(
                "# vision-managed-start\n",
                "# vision-managed-start\nagent_docs/\n",
            ),
            encoding="utf-8",
        )
        (self.runtime.agents / "default_executor.toml").write_text(
            "# local worker override\n", encoding="utf-8"
        )
        config = self.runtime.config_toml.read_text(encoding="utf-8")
        self.runtime.config_toml.write_text(
            config.replace(
                "min_wait_timeout_ms = 300000",
                'min_wait_timeout_ms = 1000\nkeep_user = "yes"',
            ),
            encoding="utf-8",
        )
        incoming_root = self.root / "incoming" / "vision"
        shutil.copytree(PACKAGE, incoming_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (incoming_root / "operate" / "VERSION").write_text(
            f"{NEXT_PACKAGE_VERSION}\n", encoding="utf-8"
        )
        user_agents = (incoming_root / "operate" / "user_AGENTS.md").read_text(encoding="utf-8")
        (incoming_root / "operate" / "user_AGENTS.md").write_text(
            user_agents.replace(
                f"vision-version: {PACKAGE_VERSION}",
                f"vision-version: {NEXT_PACKAGE_VERSION}",
            ),
            encoding="utf-8",
        )
        incoming = PackageLayout.resolve(incoming_root)
        plan_update(incoming, self.runtime, self.project).apply()
        entry = self.project.active.read_text(encoding="utf-8")
        self.assertEqual(entry, "Local policy.\n")
        self.assertEqual(
            (self.runtime.runtime / "operate" / "VERSION").read_text(),
            f"{NEXT_PACKAGE_VERSION}\n",
        )
        self.assertNotIn(
            "local worker override",
            (self.runtime.agents / "default_executor.toml").read_text(encoding="utf-8"),
        )
        updated_gitignore = gitignore.read_text(encoding="utf-8")
        self.assertNotIn("agent_docs/", updated_gitignore)
        self.assertIn(".vision_hidden_resources/", updated_gitignore)
        self.assertNotIn("AGENTS.md", updated_gitignore)
        v2_settings = tomllib.loads(self.runtime.config_toml.read_text(encoding="utf-8"))[
            "features"
        ]["multi_agent_v2"]
        self.assertEqual(v2_settings["min_wait_timeout_ms"], 300000)
        self.assertEqual(v2_settings["default_wait_timeout_ms"], 300000)
        self.assertEqual(v2_settings["max_wait_timeout_ms"], 1800000)
        self.assertEqual(v2_settings["keep_user"], "yes")
        installed_skill = self.runtime.skills / "deployment-token-report"
        self.assertEqual(
            (installed_skill / "SKILL.md").read_text(encoding="utf-8"),
            (PACKAGE / "skills" / "deployment-token-report" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
        )
        self.assertTrue(any((self.runtime.runtime / ".backups").iterdir()))

    def test_update_reconciles_obsolete_owned_runtime_and_workers(self) -> None:
        self.bootstrap()
        obsolete_runtime = self.runtime.runtime / "obsolete-owned.md"
        obsolete_runtime.write_text("obsolete\n", encoding="utf-8")
        obsolete_worker = "obsolete_worker"
        worker_definition = f"# vision-worker: {obsolete_worker}\n"
        for path in (
            self.runtime.agents / f"{obsolete_worker}.toml",
            self.runtime.runtime / "templates" / "agents" / f"{obsolete_worker}.toml",
        ):
            path.write_text(worker_definition, encoding="utf-8")
        installed_explorer = self.runtime.agents / "explorer.toml"
        installed_explorer.write_text(
            "# vision-worker: explorer\n# modified\n",
            encoding="utf-8",
        )
        state_path = self.runtime.runtime / "install_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["owned_runtime_files"].append(obsolete_runtime.name)
        state["owned_workers"].append(obsolete_worker)
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

        incoming = self.incoming_package("owned-assets-incoming", "1.2.0")
        plan_update(incoming, self.runtime, self.project).apply()

        self.assertFalse(obsolete_runtime.exists())
        self.assertFalse((self.runtime.agents / f"{obsolete_worker}.toml").exists())
        self.assertFalse(
            (
                self.runtime.runtime
                / "templates"
                / "agents"
                / f"{obsolete_worker}.toml"
            ).exists()
        )
        self.assertEqual(
            installed_explorer.read_text(encoding="utf-8"),
            (incoming.agent_templates / "explorer.toml").read_text(encoding="utf-8"),
        )

    def test_update_restores_owned_skill_and_removes_stale_skill_files(self) -> None:
        self.bootstrap()
        installed_skill = self.runtime.skills / "deployment-token-report"
        (installed_skill / "SKILL.md").write_text(
            (installed_skill / "SKILL.md")
            .read_text(encoding="utf-8")
            .replace("Compile per-agent", "Locally changed per-agent"),
            encoding="utf-8",
        )
        stale = installed_skill / "stale.txt"
        stale.write_text("stale", encoding="utf-8")
        incoming = self.incoming_package("skill-update-incoming", "1.2.0")
        plan = plan_update(incoming, self.runtime, self.project)
        backup = Path(plan.details["backup"])
        plan.apply()
        self.assertEqual(
            (installed_skill / "SKILL.md").read_text(encoding="utf-8"),
            (incoming.skill_templates / "deployment-token-report" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
        )
        self.assertFalse(stale.exists())
        self.assertTrue(
            (
                backup
                / "user"
                / "skills"
                / "deployment-token-report"
                / "SKILL.md"
            ).is_file()
        )

    def test_projects_update_against_their_recorded_historical_sources(self) -> None:
        self.bootstrap()
        second_root = self.root / "second-project"
        second_root.mkdir()
        second = ProjectPaths(second_root)
        second.active.write_text("Project-owned instructions.\n", encoding="utf-8")
        plan_project_install(self.package, second).apply()

        incoming = self.incoming_package("multi-project-incoming", "1.2.0")
        plan_update(incoming, self.runtime, self.project).apply()
        second_plan = plan_update(incoming, self.runtime, second)
        self.assertEqual(second_plan.details["from_version"], "1.2.0")
        self.assertEqual(second_plan.details["project_from_version"], PACKAGE_VERSION)
        second_plan.apply()
        self.assertEqual(second.active.read_text(), "Project-owned instructions.\n")
        self.assertEqual(json.loads(second.state.read_text())["workflow_version"], "1.2.0")

    def test_cli_updates_three_projects_without_reinstalling_user_level(self) -> None:
        self.bootstrap()
        second_root = self.root / "second-project"
        second_root.mkdir()
        second = ProjectPaths(second_root)
        second.active.write_text("Project 2 local instructions.\n", encoding="utf-8")
        plan_project_install(self.package, second).apply()
        second.gitignore.write_text(
            second.gitignore.read_text(encoding="utf-8").replace(
                "# vision-managed-start\n",
                "# vision-managed-start\nagent_docs/\n",
            ),
            encoding="utf-8",
        )
        third_root = self.root / "third-project"
        third_root.mkdir()
        third = ProjectPaths(third_root)
        plan_project_install(self.package, third).apply()

        incoming = self.incoming_package("three-project-incoming", NEXT_PACKAGE_VERSION)
        docs_before = second.root / "agent_docs" / "project_overview.md"
        docs_before.write_text("Project 2 documentation.\n", encoding="utf-8")

        def run_update(project: ProjectPaths) -> dict[str, object]:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(self.runtime.runtime / "runtime" / "workflow.py"),
                    "update",
                    "--source",
                    str(incoming.root),
                    "--codex-home",
                    str(self.codex_home),
                    "--project",
                    str(project.root),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            return json.loads(completed.stdout)

        first = run_update(self.project)
        self.assertEqual(first["operation"], "update")
        self.assertEqual(first["details"]["to_version"], NEXT_PACKAGE_VERSION)

        def user_files() -> dict[str, bytes]:
            return {
                path.relative_to(self.codex_home).as_posix(): path.read_bytes()
                for path in self.codex_home.rglob("*")
                if path.is_file() and ".backups" not in path.parts
            }

        user_before = user_files()
        second_result = run_update(second)
        self.assertEqual(second_result["operation"], "project-update")
        self.assertEqual(second_result["details"]["project_from_version"], PACKAGE_VERSION)
        self.assertTrue(second_result["applied"])
        second_backup = Path(second_result["details"]["backup"])
        self.assertFalse((second_backup / "project" / "AGENTS.md").exists())
        self.assertTrue((second_backup / "project" / ".gitignore").is_file())
        self.assertFalse((second_backup / "user").exists())
        self.assertEqual(user_files(), user_before)

        third_result = run_update(third)
        self.assertEqual(third_result["operation"], "project-update")
        self.assertTrue(third_result["applied"])
        self.assertEqual(user_files(), user_before)
        self.assertFalse(third.active.exists())
        self.assertFalse(third.disabled.exists())
        self.assertEqual(second.active.read_text(), "Project 2 local instructions.\n")
        self.assertFalse(second.personalization.exists())
        self.assertNotIn("agent_docs/", second.gitignore.read_text())
        self.assertEqual(docs_before.read_text(), "Project 2 documentation.\n")
        self.assertEqual(json.loads(second.state.read_text())["workflow_version"], NEXT_PACKAGE_VERSION)

        backup_count = len(list((self.runtime.runtime / ".backups").iterdir()))
        for project in (self.project, second, third):
            result = run_update(project)
            self.assertEqual(result["status"], "already current")
            self.assertFalse(result["applied"])
            self.assertEqual(result["details"]["backup"], None)
        self.assertEqual(len(list((self.runtime.runtime / ".backups").iterdir())), backup_count)
        self.assertEqual(user_files(), user_before)

    def test_current_release_updates_project_without_downloading_zip(self) -> None:
        self.bootstrap()
        release = ReleaseSelection(
            PACKAGE_VERSION,
            parse_semver(PACKAGE_VERSION),
            f"vision-{PACKAGE_VERSION}.zip",
            "https://example/release.zip",
            "https://example/SHA256SUMS",
        )
        output = io.StringIO()
        argv = [
            "workflow.py",
            "update",
            "--codex-home",
            str(self.codex_home),
            "--project",
            str(self.project.root),
            "--json",
        ]
        with (
            mock.patch.object(workflow_cli, "select_latest", return_value=release),
            mock.patch.object(
                workflow_cli,
                "acquire",
                side_effect=AssertionError("current release must not be downloaded"),
            ),
            mock.patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(workflow_cli.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "already current")
        self.assertFalse(result["applied"])

    def test_native_project_update_does_not_require_historical_template(self) -> None:
        self.bootstrap()
        second_root = self.root / "second-project"
        second_root.mkdir()
        second = ProjectPaths(second_root)
        plan_project_install(self.package, second).apply()
        incoming = self.incoming_package("missing-history-incoming", NEXT_PACKAGE_VERSION)
        plan_update(incoming, self.runtime, self.project).apply()
        shutil.rmtree(self.runtime.runtime / ".source_backup" / PACKAGE_VERSION)
        plan_project_only_update(
            PackageLayout.resolve(self.runtime.runtime), self.runtime, second
        ).apply()
        self.assertEqual(
            json.loads(second.state.read_text())["workflow_version"],
            NEXT_PACKAGE_VERSION,
        )

    def test_legacy_wrapper_update_requires_recorded_historical_source(self) -> None:
        self.bootstrap()
        self.project.active.write_text(
            legacy_project_entry(local="Legacy local policy."), encoding="utf-8"
        )
        state = json.loads(self.project.state.read_text())
        state["workflow_version"] = "1.1.17"
        self.project.state.write_text(json.dumps(state) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "historical workflow source"):
            plan_project_only_update(
                PackageLayout.resolve(self.runtime.runtime), self.runtime, self.project
            )

    def test_cli_install_reports_installed_and_repairs_project_state(self) -> None:
        self.bootstrap()
        command = [
            sys.executable,
            "-B",
            str(self.runtime.runtime / "runtime" / "workflow.py"),
            "install",
            "--codex-home",
            str(self.codex_home),
            "--project",
            str(self.project_root),
            "--json",
        ]
        recovery = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        recovery_summary = json.loads(recovery.stdout)
        self.assertTrue(recovery_summary["applied"])
        self.assertEqual(
            set(recovery_summary["agent_actions"][0]["recovery_files"]),
            set(recovery_summary["agent_actions"][0]["framework"]),
        )
        for document in self.project.docs.glob("*.md"):
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "<!-- vision-bootstrap-template -->\n", ""
                ),
                encoding="utf-8",
            )

        installed = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout)["status"], "already installed")

        self.project.state.unlink()
        self.project.gitignore.unlink()
        repaired = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        repaired_summary = json.loads(repaired.stdout)
        self.assertTrue(repaired_summary["applied"])
        self.assertEqual(repaired_summary["agent_actions"][0]["files"], [])
        self.assertTrue(self.project.state.is_file())
        self.assertFalse(self.project.personalization.exists())
        self.assertTrue(self.project.gitignore.is_file())

    def test_update_preserves_native_project_agents(self) -> None:
        self.bootstrap(existing_agents="Native project policy.\n")
        plan_update(
            self.incoming_package("native-agents-incoming"),
            self.runtime,
            self.project,
        ).apply()
        self.assertEqual(self.project.active.read_text(), "Native project policy.\n")
        self.assertFalse(self.project.disabled.exists())

    def test_cli_install_applies_without_confirmation_flag(self) -> None:
        project_root = self.root / "cli-project"
        project_root.mkdir()
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(PACKAGE / "runtime" / "workflow.py"),
                "install",
                "--package-root",
                str(PACKAGE),
                "--codex-home",
                str(self.codex_home),
                "--project",
                str(project_root),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertTrue(summary["applied"])
        self.assertEqual(len(summary["agent_actions"]), 1)
        self.assertTrue(summary["agent_actions"][0]["required"])
        self.assertEqual(
            summary["agent_actions"][0]["required_context_files"],
            [
                "project_structure.md",
                "project_overview.md",
                "project_core_tech.md",
            ],
        )
        self.assertFalse((project_root / "AGENTS.md").exists())

    def test_remove_requires_second_confirmation_and_cleans_owned_files(self) -> None:
        self.bootstrap(existing_agents="Local policy.\n")
        legacy_resource = (
            self.project.hidden_dir
            / "deployments"
            / "feature_a"
            / "verification"
            / "record.json"
        )
        legacy_resource.parent.mkdir(parents=True)
        legacy_resource.write_text("{}\n", encoding="utf-8")
        user_agents = self.runtime.user_agents.read_text(encoding="utf-8")
        self.runtime.user_agents.write_text(
            "# Keep this user policy.\n\n" + user_agents,
            encoding="utf-8",
        )
        config = self.runtime.config_toml.read_text(encoding="utf-8")
        config = config.replace(
            "[agents]\nenabled = true",
            "[agents]\nenabled = true\nkeep_agent = true",
        )
        config = config.replace(
            "[features]\nmulti_agent = true",
            '[features]\nmulti_agent = true\nkeep_feature = "keep"',
        )
        config = config.replace('model = "gpt-6-sol"', 'model = "keep"', 1)
        self.runtime.config_toml.write_text(config, encoding="utf-8")
        unrelated_worker = self.runtime.agents / "unrelated.toml"
        unrelated_worker.write_text('model = "keep"\n', encoding="utf-8")
        unrelated_skill = self.runtime.skills / "unrelated-skill"
        unrelated_skill.mkdir(parents=True)
        (unrelated_skill / "SKILL.md").write_text(
            "---\nname: unrelated-skill\ndescription: keep\n---\n",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-B",
            str(self.runtime.runtime / "runtime" / "workflow.py"),
            "remove",
            "--codex-home",
            str(self.codex_home),
            "--project",
            str(self.project_root),
            "--json",
        ]
        planned = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        planned_summary = json.loads(planned.stdout)
        self.assertFalse(planned_summary["applied"])
        self.assertTrue(planned_summary["confirmation_required"])
        self.assertTrue(
            any("legacy project workflow resources" in warning for warning in planned_summary["warnings"])
        )
        self.assertTrue(self.project.active.is_file())
        self.assertTrue(self.runtime.runtime.is_dir())

        confirmed = subprocess.run(
            [*command[:-1], "--confirm", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.assertTrue(json.loads(confirmed.stdout)["applied"])
        self.assertEqual(self.project.active.read_text(encoding="utf-8"), "Local policy.\n")
        self.assertFalse(self.project.hidden_dir.exists())
        self.assertTrue((self.project.docs / "project_overview.md").is_file())
        self.assertFalse(self.runtime.runtime.exists())
        self.assertTrue(unrelated_worker.is_file())
        self.assertTrue((unrelated_skill / "SKILL.md").is_file())
        self.assertFalse(
            (self.runtime.skills / "deployment-token-report").exists()
        )
        self.assertEqual(
            self.runtime.user_agents.read_text(encoding="utf-8"),
            "# Keep this user policy.\n",
        )
        remaining_config = self.runtime.config_toml.read_text(encoding="utf-8")
        self.assertIn('model = "keep"', remaining_config)
        self.assertIn("keep_agent = true", remaining_config)
        self.assertIn('keep_feature = "keep"', remaining_config)
        self.assertNotIn("max_concurrent_threads_per_session", remaining_config)
        self.assertNotIn("[features.multi_agent_v2]", remaining_config)

    def test_update_allows_missing_optional_codex_config(self) -> None:
        self.bootstrap()
        self.runtime.config_toml.unlink()
        plan = plan_update(
            self.incoming_package("missing-config-incoming"),
            self.runtime,
            self.project,
        )
        self.assertEqual(plan.operation, "update")

    def test_update_rejects_unsafe_owned_runtime_state(self) -> None:
        self.bootstrap()
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        state_path = self.runtime.runtime / "install_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["owned_runtime_files"] = ["../../outside.txt"]
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            plan_update(
                self.incoming_package("unsafe-state-incoming"),
                self.runtime,
                self.project,
            )
        self.assertTrue(outside.is_file())

    def test_update_rejects_unsafe_owned_skill_state(self) -> None:
        self.bootstrap()
        state_path = self.runtime.runtime / "install_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["owned_skills"] = ["../../outside"]
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "unsafe name"):
            plan_update(
                self.incoming_package("unsafe-skill-state-incoming"),
                self.runtime,
                self.project,
            )

    def test_legacy_entry_with_edits_requires_reviewed_local_instructions(self) -> None:
        self.bootstrap()
        installed_template_path = self.runtime.runtime / "templates" / "AGENTS.md"
        legacy_template = legacy_project_entry()
        legacy_template = legacy_template.replace(
            "<!-- vision-managed-start -->\n", ""
        ).replace("<!-- vision-managed-end -->\n\n", "")
        legacy_template = legacy_template.replace(
            "\n<!-- vision-project-local-instructions-start -->\n"
            "<!-- vision-project-local-instructions-end -->\n",
            "\n",
        )
        installed_template_path.write_text(legacy_template, encoding="utf-8")
        self.project.active.write_text(
            legacy_template + "\nLocal legacy addition.\n", encoding="utf-8"
        )
        incoming = self.incoming_package("legacy-incoming")
        with self.assertRaises(ValidationError):
            plan_update(incoming, self.runtime, self.project)
        plan_update(
            incoming,
            self.runtime,
            self.project,
            legacy_local_instructions="Local legacy addition.",
        ).apply()
        self.assertEqual(
            self.project.active.read_text(encoding="utf-8"),
            "Local legacy addition.\n",
        )

    def test_update_repairs_missing_legacy_route_in_local_region(self) -> None:
        self.bootstrap()
        self.project.active.write_text(
            legacy_project_entry(
                local="Read `agent_docs/workflows/heavy_route.md`."
            ),
            encoding="utf-8",
        )
        incoming = self.incoming_package("legacy-route-incoming")
        with self.assertRaisesRegex(ValidationError, "missing legacy workflow route"):
            plan_update(incoming, self.runtime, self.project)

        plan_update(
            incoming,
            self.runtime,
            self.project,
            legacy_local_instructions="Project policy.",
        ).apply()
        self.assertEqual(
            self.project.active.read_text(encoding="utf-8"),
            "Project policy.\n",
        )

    def test_update_rejects_drift_in_workflow_managed_region(self) -> None:
        self.bootstrap()
        installed_template_path = self.runtime.runtime / "templates" / "AGENTS.md"
        installed_template_path.write_text(legacy_project_entry(), encoding="utf-8")
        self.project.active.write_text(
            legacy_project_entry().replace(
                "# Legacy Workflow Policy", "# Locally Changed Workflow Policy"
            ),
            encoding="utf-8",
        )
        incoming = self.incoming_package("drift-incoming")
        with self.assertRaises(ValidationError):
            plan_update(incoming, self.runtime, self.project)

    def test_installed_launcher_delegates_to_incoming_update_runtime(self) -> None:
        self.bootstrap()
        incoming_root = self.root / "delegated-incoming" / "vision"
        shutil.copytree(
            PACKAGE,
            incoming_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (incoming_root / "operate" / "VERSION").write_text(
            f"{NEXT_PACKAGE_VERSION}\n", encoding="utf-8"
        )
        user_agents = (incoming_root / "operate" / "user_AGENTS.md").read_text(encoding="utf-8")
        (incoming_root / "operate" / "user_AGENTS.md").write_text(
            user_agents.replace(
                f"vision-version: {PACKAGE_VERSION}",
                f"vision-version: {NEXT_PACKAGE_VERSION}",
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(self.runtime.runtime / "runtime" / "workflow.py"),
                "update",
                "--source",
                str(incoming_root),
                "--codex-home",
                str(self.codex_home),
                "--project",
                str(self.project_root),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["details"]["to_version"], NEXT_PACKAGE_VERSION)
        self.assertTrue(summary["applied"])

    def test_external_update_delegates_before_launcher_validation(self) -> None:
        self.bootstrap()
        incoming_root = self.root / "unvalidated-incoming" / "vision"
        shutil.copytree(
            PACKAGE,
            incoming_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (incoming_root / "operate" / "VERSION").write_text(
            f"{NEXT_PACKAGE_VERSION}\n", encoding="utf-8"
        )

        argv = [
            str(PACKAGE / "runtime" / "workflow.py"),
            "update",
            "--source",
            str(incoming_root),
            "--codex-home",
            str(self.codex_home),
            "--project",
            str(self.project_root),
            "--json",
        ]
        with (
            mock.patch.object(
                workflow_cli.PackageLayout,
                "resolve",
                side_effect=AssertionError(
                    "external package was validated by launcher"
                ),
            ) as resolve,
            mock.patch.object(
                workflow_cli, "_delegate_update", return_value=0
            ) as delegate,
            mock.patch.object(sys, "argv", argv),
        ):
            self.assertEqual(workflow_cli.main(), 0)

        resolve.assert_not_called()
        delegate.assert_called_once()
        self.assertEqual(delegate.call_args.args[0], incoming_root.resolve())


class OpenCodePlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.opencode_home = self.root / "opencode-home"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.project = ProjectPaths(self.project_root)
        self.package = PackageLayout.resolve(PACKAGE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bootstrap(self, platforms: list[str] | None = None) -> None:
        from runtime.platform_lifecycle import plan_platform_bootstrap

        plan_platform_bootstrap(
            self.package,
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=platforms or ["opencode"],
            project=self.project,
        ).apply()

    def adapter(self):
        from runtime.platforms import adapter_for

        return adapter_for("opencode", opencode_home=self.opencode_home)

    def test_open_code_bootstrap_installs_native_subagents(self) -> None:
        self.bootstrap()
        agents = self.opencode_home / "agents"
        for role in self.package.worker_names | {"default_executor"}:
            self.assertTrue((agents / f"{role}.md").is_file(), role)
        explorer = (agents / "explorer.md").read_text(encoding="utf-8")
        self.assertIn("mode: subagent", explorer)
        self.assertIn("edit: deny", explorer)
        self.assertIn("bash: deny", explorer)
        self.assertIn("task: deny", explorer)
        executor = (agents / "default_executor.md").read_text(encoding="utf-8")
        self.assertIn("edit: allow", executor)
        self.assertIn("bash: allow", executor)
        self.assertNotIn("{{VISION_HOME}}", explorer)
        instructions = (self.opencode_home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- vision-user-managed-start -->", instructions)
        self.assertIn("~/.config/opencode/vision/operate/install.md", instructions)
        self.assertNotIn("~/.codex", instructions)
        state = json.loads(
            (
                self.opencode_home / "vision" / "install_state.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(state["platform"], "opencode")
        self.assertEqual(state["platforms"], ["opencode"])
        self.assertEqual(
            set(state["owned_workers"]),
            self.package.worker_names | {"default_executor"},
        )
        self.assertTrue(
            (
                self.opencode_home
                / "skills"
                / "deployment-token-report"
                / "scripts"
                / "report_tokens_opencode.py"
            ).is_file()
        )
        self.assertFalse(self.codex_home.exists())

    def test_codex_only_bootstrap_does_not_touch_opencode(self) -> None:
        from runtime.platform_lifecycle import plan_platform_bootstrap

        plan_platform_bootstrap(
            self.package,
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["codex"],
            project=self.project,
        ).apply()
        self.assertTrue((self.codex_home / "vision" / "runtime" / "workflow.py").is_file())
        self.assertFalse(self.opencode_home.exists())

    def test_both_bootstrap_records_and_isolates_platforms(self) -> None:
        self.bootstrap(["codex", "opencode"])
        self.assertTrue((self.codex_home / "agents" / "explorer.toml").is_file())
        self.assertTrue((self.opencode_home / "agents" / "explorer.md").is_file())
        codex_state = json.loads(
            (self.codex_home / "vision" / "install_state.json").read_text(encoding="utf-8")
        )
        opencode_state = json.loads(
            (self.opencode_home / "vision" / "install_state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(codex_state["platforms"], ["codex", "opencode"])
        self.assertEqual(opencode_state["platforms"], ["codex", "opencode"])

    def test_open_code_worker_model_config_regenerates_agent(self) -> None:
        from runtime.platform_lifecycle import plan_platform_config

        self.bootstrap()
        plan = plan_platform_config(
            key="explorer",
            value="anthropic/claude-sonnet-4-5#high",
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["opencode"],
        )
        plan.apply()
        explorer = (self.opencode_home / "agents" / "explorer.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("model: anthropic/claude-sonnet-4-5", explorer)
        self.assertIn("reasoningEffort: high", explorer)
        config = json.loads(
            (self.opencode_home / "vision" / "config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["worker_models"]["explorer"], "anthropic/claude-sonnet-4-5#high"
        )

    def test_open_code_config_rejects_invalid_model_id(self) -> None:
        from runtime.platform_lifecycle import plan_platform_config

        self.bootstrap()
        with self.assertRaisesRegex(ValidationError, "invalid OpenCode model id"):
            plan_platform_config(
                key="explorer",
                value="not-a-native-id",
                codex_home=self.codex_home,
                opencode_home=self.opencode_home,
                platforms=["opencode"],
            )

    def test_open_code_update_regenerates_and_preserves_models(self) -> None:
        from runtime.platform_lifecycle import plan_opencode_update, plan_platform_config

        self.bootstrap()
        plan_platform_config(
            key="explorer",
            value="openai/gpt-5.1-codex#high",
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["opencode"],
        ).apply()
        (self.opencode_home / "agents" / "explorer.md").write_text(
            "# locally changed\n", encoding="utf-8"
        )
        stale = self.opencode_home / "vision" / "stale-owned.md"
        stale.write_text("stale\n", encoding="utf-8")
        state_path = self.opencode_home / "vision" / "install_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["owned_runtime_files"].append("stale-owned.md")
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        incoming_root = self.root / "incoming" / "vision"
        shutil.copytree(PACKAGE, incoming_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (incoming_root / "operate" / "VERSION").write_text(
            f"{NEXT_PACKAGE_VERSION}\n", encoding="utf-8"
        )
        user_agents = (incoming_root / "operate" / "user_AGENTS.md").read_text(encoding="utf-8")
        (incoming_root / "operate" / "user_AGENTS.md").write_text(
            user_agents.replace(
                f"vision-version: {PACKAGE_VERSION}",
                f"vision-version: {NEXT_PACKAGE_VERSION}",
            ),
            encoding="utf-8",
        )
        incoming = PackageLayout.resolve(incoming_root)
        plan = plan_opencode_update(
            incoming, self.adapter(), self.project, platforms=["opencode"]
        )
        plan.apply()
        explorer = (self.opencode_home / "agents" / "explorer.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("model: openai/gpt-5.1-codex", explorer)
        self.assertNotIn("locally changed", explorer)
        self.assertFalse(stale.exists())
        self.assertEqual(
            (self.opencode_home / "vision" / "operate" / "VERSION").read_text().strip(),
            NEXT_PACKAGE_VERSION,
        )
        config = json.loads(
            (self.opencode_home / "vision" / "config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["worker_models"]["explorer"], "openai/gpt-5.1-codex#high"
        )
        self.assertFalse(self.codex_home.exists())

    def test_open_code_remove_preserves_codex_and_unrelated_resources(self) -> None:
        from runtime.platform_lifecycle import plan_platform_remove

        self.bootstrap(["codex", "opencode"])
        unrelated_agent = self.opencode_home / "agents" / "unrelated.md"
        unrelated_agent.write_text("---\ndescription: keep\n---\nkeep\n", encoding="utf-8")
        unrelated_skill = self.opencode_home / "skills" / "unrelated-skill"
        unrelated_skill.mkdir(parents=True)
        (unrelated_skill / "SKILL.md").write_text(
            "---\nname: unrelated-skill\ndescription: keep\n---\n",
            encoding="utf-8",
        )
        user_agents = self.opencode_home / "AGENTS.md"
        user_agents.write_text(
            "# Keep this user policy.\n\n" + user_agents.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        plan_platform_remove(
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["opencode"],
            project=self.project,
        ).apply()
        self.assertFalse((self.opencode_home / "vision").exists())
        self.assertFalse((self.opencode_home / "agents" / "explorer.md").exists())
        self.assertTrue(unrelated_agent.is_file())
        self.assertTrue((unrelated_skill / "SKILL.md").is_file())
        self.assertEqual(
            user_agents.read_text(encoding="utf-8"), "# Keep this user policy.\n"
        )
        self.assertTrue((self.codex_home / "vision" / "runtime" / "workflow.py").is_file())
        self.assertTrue((self.codex_home / "agents" / "explorer.toml").is_file())

    def test_both_remove_cleans_each_installed_platform(self) -> None:
        from runtime.platform_lifecycle import plan_platform_remove

        self.bootstrap(["codex", "opencode"])
        plan_platform_remove(
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["codex", "opencode"],
            project=self.project,
        ).apply()
        self.assertFalse((self.codex_home / "vision").exists())
        self.assertFalse((self.codex_home / "agents" / "explorer.toml").exists())
        self.assertFalse((self.opencode_home / "vision").exists())
        self.assertFalse((self.opencode_home / "agents" / "explorer.md").exists())

    def test_resolve_platforms_prefers_recorded_installation(self) -> None:
        from runtime.platform_lifecycle import resolve_platforms

        self.bootstrap(["opencode"])
        self.assertEqual(
            resolve_platforms(
                None,
                codex_home=self.codex_home,
                opencode_home=self.opencode_home,
                prompt=False,
            ),
            ["opencode"],
        )
        self.assertEqual(
            resolve_platforms(
                "both",
                codex_home=self.codex_home,
                opencode_home=self.opencode_home,
                prompt=False,
            ),
            ["codex", "opencode"],
        )


class NativeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex-home"
        self.opencode_home = self.root / "opencode-home"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.project = ProjectPaths(self.project_root)
        self.package = PackageLayout.resolve(PACKAGE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def bootstrap(self, platforms: list[str]) -> None:
        from runtime.platform_lifecycle import plan_platform_bootstrap

        plan_platform_bootstrap(
            self.package,
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=platforms,
            project=self.project,
        ).apply()

    def codex_adapter(self):
        from runtime.platforms import adapter_for

        return adapter_for("codex", codex_home=self.codex_home)

    def opencode_adapter(self):
        from runtime.platforms import adapter_for

        return adapter_for("opencode", opencode_home=self.opencode_home)

    def incoming_package(self) -> PackageLayout:
        incoming_root = self.root / "incoming" / "vision"
        shutil.copytree(
            PACKAGE, incoming_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        (incoming_root / "operate" / "VERSION").write_text(
            f"{NEXT_PACKAGE_VERSION}\n", encoding="utf-8"
        )
        user_agents = (incoming_root / "operate" / "user_AGENTS.md").read_text(
            encoding="utf-8"
        )
        (incoming_root / "operate" / "user_AGENTS.md").write_text(
            user_agents.replace(
                f"vision-version: {PACKAGE_VERSION}",
                f"vision-version: {NEXT_PACKAGE_VERSION}",
            ),
            encoding="utf-8",
        )
        return PackageLayout.resolve(incoming_root)

    def test_command_mapping_is_canonical(self) -> None:
        from runtime.commands import COMMAND_NAMES, COMMANDS_BY_NAME

        self.assertEqual(
            COMMAND_NAMES,
            ("light", "medium", "heavy", "install", "update", "config", "remove"),
        )
        self.assertEqual(COMMANDS_BY_NAME["heavy"].route, "Heavy")
        self.assertEqual(COMMANDS_BY_NAME["heavy"].route_doc, "heavy_route.md")
        self.assertEqual(COMMANDS_BY_NAME["update"].guide, "update.md")
        self.assertEqual(COMMANDS_BY_NAME["config"].action, "config")

    def test_codex_commands_install_and_validate(self) -> None:
        self.bootstrap(["codex"])
        found = self.codex_adapter().validate_commands()
        self.assertEqual(
            sorted(found),
            ["config", "heavy", "install", "light", "medium", "remove", "update"],
        )
        for name in found:
            skill = self.codex_home / "skills" / f"vision-{name}" / "SKILL.md"
            self.assertTrue(skill.is_file(), name)
            self.assertIn(f"<!-- vision-command: {name} -->", skill.read_text(encoding="utf-8"))
            self.assertTrue(
                (
                    self.codex_home / "skills" / f"vision-{name}" / "agents" / "openai.yaml"
                ).is_file(),
                name,
            )
        heavy = (self.codex_home / "skills" / "vision-heavy" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("~/.codex/vision/heavy_route.md", heavy)
        self.assertIn("use heavy route.", heavy)
        self.assertNotIn("{{VISION_HOME}}", heavy)
        self.assertFalse((self.codex_home / "prompts").exists())

    def test_opencode_commands_install_and_validate(self) -> None:
        self.bootstrap(["opencode"])
        found = self.opencode_adapter().validate_commands()
        self.assertEqual(
            sorted(found),
            ["config", "heavy", "install", "light", "medium", "remove", "update"],
        )
        heavy = (self.opencode_home / "commands" / "heavy.md").read_text(encoding="utf-8")
        self.assertIn("Task: $ARGUMENTS", heavy)
        self.assertIn("~/.config/opencode/vision/heavy_route.md", heavy)
        self.assertIn("**Heavy**", heavy)
        self.assertNotIn("{{VISION_HOME}}", heavy)
        config = (self.opencode_home / "commands" / "config.md").read_text(encoding="utf-8")
        self.assertIn("runtime/workflow.py config --key", config)
        self.assertFalse((self.opencode_home / "prompts").exists())

    def test_lifecycle_commands_call_runtime_and_routes_reference_shared_contract(self) -> None:
        self.bootstrap(["codex", "opencode"])
        codex_update = (
            self.codex_home / "skills" / "vision-update" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("runtime/workflow.py update --project", codex_update)
        self.assertIn("operate/update.md", codex_update)
        opencode_remove = (self.opencode_home / "commands" / "remove.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("runtime/workflow.py remove --project", opencode_remove)
        opencode_medium = (self.opencode_home / "commands" / "medium.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("medium_route.md", opencode_medium)
        self.assertNotIn("## Main Ownership", opencode_medium)

    def test_both_install_command_surfaces(self) -> None:
        from runtime.commands import COMMAND_NAMES

        self.bootstrap(["codex", "opencode"])
        self.assertTrue((self.codex_home / "skills" / "vision-light" / "SKILL.md").is_file())
        self.assertTrue((self.opencode_home / "commands" / "light.md").is_file())
        codex_state = json.loads(
            (self.codex_home / "vision" / "install_state.json").read_text(encoding="utf-8")
        )
        opencode_state = json.loads(
            (self.opencode_home / "vision" / "install_state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(codex_state["owned_commands"], sorted(COMMAND_NAMES))
        self.assertEqual(opencode_state["owned_commands"], sorted(COMMAND_NAMES))

    def test_update_refreshes_commands(self) -> None:
        from runtime.platform_lifecycle import plan_platform_update

        self.bootstrap(["codex", "opencode"])
        opencode_heavy = self.opencode_home / "commands" / "heavy.md"
        opencode_heavy.write_text(
            opencode_heavy.read_text(encoding="utf-8") + "\nlocal note\n",
            encoding="utf-8",
        )
        codex_heavy = self.codex_home / "skills" / "vision-heavy" / "SKILL.md"
        codex_heavy.write_text(
            codex_heavy.read_text(encoding="utf-8") + "\nlocal note\n",
            encoding="utf-8",
        )
        incoming = self.incoming_package()
        plan_platform_update(
            incoming,
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["codex", "opencode"],
            project=self.project,
        ).apply()
        self.assertIn("$ARGUMENTS", opencode_heavy.read_text(encoding="utf-8"))
        self.assertNotIn("local note", opencode_heavy.read_text(encoding="utf-8"))
        self.assertIn("vision-command: heavy", codex_heavy.read_text(encoding="utf-8"))
        self.assertNotIn("local note", codex_heavy.read_text(encoding="utf-8"))

    def test_remove_only_vision_command_resources(self) -> None:
        from runtime.platform_lifecycle import plan_platform_remove

        self.bootstrap(["codex", "opencode"])
        (self.opencode_home / "commands" / "custom.md").write_text(
            "---\ndescription: mine\n---\nkeep\n", encoding="utf-8"
        )
        unrelated_opencode = self.opencode_home / "skills" / "my-skill"
        unrelated_opencode.mkdir(parents=True)
        (unrelated_opencode / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: keep\n---\n", encoding="utf-8"
        )
        unrelated_codex = self.codex_home / "skills" / "notes"
        unrelated_codex.mkdir(parents=True)
        (unrelated_codex / "SKILL.md").write_text(
            "---\nname: notes\ndescription: keep\n---\n", encoding="utf-8"
        )
        plan_platform_remove(
            codex_home=self.codex_home,
            opencode_home=self.opencode_home,
            platforms=["codex", "opencode"],
            project=self.project,
        ).apply()
        self.assertTrue((self.opencode_home / "commands" / "custom.md").is_file())
        self.assertTrue((unrelated_opencode / "SKILL.md").is_file())
        self.assertTrue((unrelated_codex / "SKILL.md").is_file())
        self.assertFalse((self.opencode_home / "commands" / "heavy.md").exists())
        self.assertFalse((self.codex_home / "skills" / "vision-heavy").exists())
        self.assertFalse((self.codex_home / "skills" / "vision-update").exists())

    def test_validate_commands_rejects_tampered_owned_command(self) -> None:
        self.bootstrap(["codex", "opencode"])
        (self.opencode_home / "commands" / "heavy.md").write_text(
            "---\ndescription: x\n---\nno marker\n", encoding="utf-8"
        )
        (self.codex_home / "skills" / "vision-heavy" / "SKILL.md").write_text(
            "# no marker\n", encoding="utf-8"
        )
        with self.assertRaises(ValidationError):
            self.opencode_adapter().validate_commands()
        with self.assertRaises(ValidationError):
            self.codex_adapter().validate_commands()


if __name__ == "__main__":
    unittest.main()
