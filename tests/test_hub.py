from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub import agents, evolution, repos, security, work
from agent_hub.cli import service
from agent_hub.common import CORE, HubError, git, read_json, run, save, toml_string, write
from agent_hub.config import Config


def commit(path, message="fixture"):
    git(path, "add", "--all")
    return git(path, "-c", "user.name=Hub Test", "-c", "user.email=hub@example.invalid", "commit", "-m", message)


def repository(path):
    path.mkdir()
    run(["git", "init", "-b", "main", path])
    write(path / "example.txt", "original\n")
    commit(path)
    git(path, "remote", "add", "origin", "https://github.com/example/" + path.name + ".git")
    return path


class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.TemporaryDirectory(prefix="hub-suite-")
        cls.source = Path(cls.storage.name) / "core"
        cls.source.mkdir()
        for directory in ["agent_hub", "bin", "prompts", "templates"]:
            shutil.copytree(CORE / directory, cls.source / directory, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(CORE / "pyproject.toml", cls.source / "pyproject.toml")
        write(cls.source / ".gitignore", "__pycache__/\n*.py[cod]\n")
        # Candidate fixtures have an executable CLI smoke check, not a recursive copy of this suite.
        write(cls.source / "tests/test_smoke.py", "import subprocess,sys,unittest\nclass Smoke(unittest.TestCase):\n def test_cli(self):\n  r=subprocess.run([sys.executable,'bin/hub','--help'],capture_output=True,text=True)\n  self.assertEqual(r.returncode,0)\n  self.assertIn('Agent Hub',r.stdout)\n")
        run(["git", "init", "-b", "main", cls.source])
        commit(cls.source)
        cls.first = git(cls.source, "rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hub-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.instance = self.root / "instance"
        evolution.init(self.instance, "test", str(self.source), ref=self.first)
        with (self.instance / "local.toml").open("a") as stream:
            stream.write("\n[tools]\ncodex = " + toml_string(sys.executable) + "\n")
        self.repo = repository(self.root / "alpha")
        self.register()

    def register(self, text=None):
        if text is None:
            text = f'[[repos]]\nname="alpha"\nremote="https://github.com/example/alpha.git"\ndefault_branch="main"\nprotected=true\nvisible=true\n'
        write(self.instance / "repos.toml", text)
        self.config = Config(self.instance)

    def unit(self, names=None):
        unit = work.create(self.config, "Bounded task", "Improve a fixture", names if names is not None else ["alpha"], "Check fixture content")
        work.prepare(self.config, unit["id"])
        return unit

    def test_independent_histories(self):
        self.assertNotEqual(git(self.instance, "rev-parse", "--git-dir"), "")
        self.assertNotEqual(self.config.lock["commit"], "")
        self.assertEqual(git(self.instance, "rev-list", "--all", check=False), "")
        self.assertNotEqual(git(self.source, "rev-list", "--all"), "")

    def test_init_replay_preserves_configuration(self):
        before = (self.instance / "repos.toml").read_bytes()
        result = evolution.init(self.instance, "ignored", str(self.source))
        self.assertFalse(result["created"])
        self.assertEqual(before, (self.instance / "repos.toml").read_bytes())

    def test_init_nonempty_refused(self):
        p = self.root / "existing"
        p.mkdir()
        write(p / "private.txt", "private")
        with self.assertRaises(HubError):
            evolution.init(p, "test", str(self.source))
        self.assertEqual((p / "private.txt").read_text(), "private")

    def test_config_wrong_schema(self):
        write(self.instance / "hub.toml", 'schema_version=2\n[instance]\nname="test"\n')
        with self.assertRaises(HubError):
            Config(self.instance)

    def test_duplicate_repo_rejected(self):
        text = (self.instance / "repos.toml").read_text()
        with self.assertRaises(HubError):
            self.register(text + text)

    def test_path_escape_rejected(self):
        with self.assertRaises(HubError):
            self.register((self.instance / "repos.toml").read_text() + 'folder="../../escape"\n')

    def test_credential_remote_rejected(self):
        with self.assertRaises(HubError):
            self.register('[[repos]]\nname="bad"\nremote="https://user:' + 'pass@example.com/repo"\n')

    def test_overlay_is_external_reference(self):
        overlay = self.root / "overlay.toml"
        write(overlay, '[[resources]]\nname="notes"\nkind="context"\npath="../missing-notes"\n')
        text = (self.instance / "local.toml").read_text()
        write(self.instance / "local.toml", 'overlay=' + toml_string(overlay) + "\n" + text)
        cfg = Config(self.instance)
        self.assertEqual(cfg.resources[0]["name"], "notes")
        self.assertNotIn("notes", (self.instance / "hub.toml").read_text())

    def test_existing_attachment(self):
        row = repos.inspect(self.config.repo("alpha"))
        self.assertTrue(row["available"])
        before = git(self.repo, "status", "--porcelain")
        repos.bootstrap(self.config)
        self.assertEqual(before, git(self.repo, "status", "--porcelain"))

    def test_wrong_remote_rejected(self):
        git(self.repo, "remote", "set-url", "origin", "https://github.com/example/wrong.git")
        self.assertFalse(repos.inspect(self.config.repo("alpha"))["available"])
        with self.assertRaises(HubError):
            self.unit()

    def test_wrong_root_rejected(self):
        (self.repo / "nested").mkdir()
        with (self.instance / "local.toml").open("a") as stream:
            stream.write('\n[repos.alpha]\npath=' + toml_string(self.repo / "nested") + '\n')
        self.assertFalse(repos.inspect(Config(self.instance).repo("alpha"))["available"])

    def test_missing_repository_not_cloned_implicitly(self):
        self.register('[[repos]]\nname="missing"\nremote="https://github.com/example/missing.git"\ncheckout=false\n')
        self.assertFalse(repos.bootstrap(self.config)[0]["available"])
        self.assertFalse((self.root / "missing").exists())

    def test_clone_and_replay(self):
        self.register('[[repos]]\nname="cloned"\nremote=' + toml_string(self.repo) + '\ncheckout=true\n')
        self.assertTrue(repos.bootstrap(self.config)[0]["available"])
        self.assertTrue(repos.bootstrap(self.config)[0]["available"])

    def test_visibility_independent_of_availability(self):
        text = (self.instance / "repos.toml").read_text().replace("visible=true", "visible=false")
        self.register(text)
        self.assertTrue(repos.inspect(self.config.repo("alpha"))["available"])
        self.assertNotIn("alpha", repos.workspace(self.config)["folders"])

    def test_workspace_process_tasks_and_pinned_runtime(self):
        result = repos.workspace(self.config)
        data = read_json(Path(result["workspace"]))
        self.assertEqual(data["tasks"]["tasks"][0]["type"], "process")
        self.assertIn(self.first, data["tasks"]["tasks"][0]["args"][0])
        self.assertIn("alpha", result["folders"])

    def test_discovery_explicit_and_nonrecursive_inside_repo(self):
        write(self.repo / "private" / "do-not-read.md", "private")
        rows = repos.discover([str(self.root)], depth=2)
        self.assertIn("alpha", [x.get("name") for x in rows])
        self.assertNotIn("private", json.dumps(rows))
        with self.assertRaises(HubError):
            repos.discover([])

    def test_missing_resources_not_connected(self):
        with (self.instance / "hub.toml").open("a") as stream:
            stream.write('\n[[resources]]\nname="notes"\nkind="context"\npath="../absent"\n\n[[resources]]\nname="mcp"\nkind="mcp"\nlocation="native config"\n')
        rows = repos.resources(Config(self.instance))
        self.assertFalse(rows[0]["available"])
        self.assertIn("unsupported", rows[1]["connectivity"])

    def test_doctor_detects_wrong_repository(self):
        git(self.repo, "remote", "set-url", "origin", "https://github.com/example/wrong.git")
        self.assertFalse(repos.doctor(self.config)["ready"])

    def test_doctor_installed_runtime_does_not_verify_execution(self):
        result = repos.doctor(self.config)
        self.assertTrue(result["ready"])
        self.assertEqual(result["agent_execution"], {
            "runtime": "codex", "launch_adapter_implemented": True,
            "last_sandbox_probe": {"runtime": "codex", "status": "not-probed"},
            "worker_execution": "unverified"})
        self.assertIn("Not inferred", result["authentication"])

    def test_doctor_reports_saved_sandbox_probe_outcomes(self):
        for passed, code, checks, expected in [
            (True, 0, {"inside_write": True, "outside_and_metadata_blocked": [True, True]}, "passed"),
            (False, 1, {"reason": "Runtime cannot enforce the requested sandbox"}, "blocked"),
        ]:
            with self.subTest(status=expected):
                save(self.instance / ".hub/last-sandbox-probe.json", {
                    "passed": passed, "exit_code": code, "checks": checks,
                    "runtime": "codex fixture", "scope": "local filesystem command boundary"})
                result = repos.doctor(self.config)
                self.assertTrue(result["ready"])
                self.assertEqual(result["agent_execution"]["last_sandbox_probe"]["status"], expected)
                self.assertEqual(result["agent_execution"]["worker_execution"], "unverified")

    def test_doctor_malformed_sandbox_probe_is_unknown(self):
        reports = ["[" * 2000, "{", "[]", "null", '"passed"', '{}', '{"passed": true}',
                   '{"passed": "false", "exit_code": 1, "checks": {}}',
                   '{"passed": true, "exit_code": false, "checks": {}}',
                   '{"passed": false, "exit_code": 0, "checks": {}}',
                   '{"passed": true, "exit_code": 1, "checks": {}}',
                   '{"passed": true, "exit_code": 0, "checks": {"inside_write": true, "outside_and_metadata_blocked": []}}',
                   '{"passed": true, "exit_code": 0, "checks": {"inside_write": true, "outside_and_metadata_blocked": [1]}}',
                   '{"passed": true, "exit_code": 0, "checks": {"inside_write": true, "outside_and_metadata_blocked": [false]}}']
        for report in reports:
            with self.subTest(report=report):
                write(self.instance / ".hub/last-sandbox-probe.json", report)
                result = repos.doctor(self.config)
                self.assertTrue(result["ready"])
                self.assertEqual(result["agent_execution"]["last_sandbox_probe"]["status"], "unknown")

    def test_doctor_unreadable_sandbox_probe_is_unknown(self):
        path = self.instance / ".hub/last-sandbox-probe.json"
        path.write_bytes(b"\xff")
        self.assertEqual(repos.doctor(self.config)["agent_execution"]["last_sandbox_probe"]["status"], "unknown")
        path.unlink()
        path.mkdir()
        self.assertEqual(repos.doctor(self.config)["agent_execution"]["last_sandbox_probe"]["status"], "unknown")

    def test_doctor_claude_has_no_launch_adapter(self):
        save(self.instance / ".hub/last-sandbox-probe.json", {
            "passed": True, "exit_code": 0,
            "checks": {"inside_write": True, "outside_and_metadata_blocked": [True]}})
        self.config.runtime = "claude"
        with patch("agent_hub.repos.executable", return_value=sys.executable):
            result = repos.doctor(self.config)
        self.assertTrue(result["ready"])
        self.assertEqual(result["agent_execution"]["runtime"], "claude")
        self.assertFalse(result["agent_execution"]["launch_adapter_implemented"])
        self.assertEqual(result["agent_execution"]["last_sandbox_probe"], {"runtime": "codex", "status": "passed"})
        self.assertEqual(result["agent_execution"]["worker_execution"], "unverified")

    def test_worktree_preserves_original(self):
        unit = self.unit()
        p = work.location(self.config, unit["id"], "alpha")
        write(p / "example.txt", "worker change\n")
        self.assertEqual((self.repo / "example.txt").read_text(), "original\n")
        self.assertTrue(work.status(self.config, unit["id"])[0]["repos"]["alpha"]["dirty"])

    def test_prepare_idempotent(self):
        unit = self.unit()
        work.prepare(self.config, unit["id"])
        self.assertEqual(len(work.status(self.config)), 1)

    def test_prepare_includes_source_context_contract(self):
        source = {"provider": "example-tracker", "id": "example-42",
                  "url": "https://example.com/tickets/42"}
        unit = work.create(self.config, "Sourced task", "Improve a fixture", ["alpha"],
                           "Check fixture content", source=source)
        work.prepare(self.config, unit["id"])
        root = work.location(self.config, unit["id"])
        instructions = (root / "AGENTS.md").read_text()
        for line in ("- Provider: example-tracker", "- ID: example-42",
                     "- URL: https://example.com/tickets/42"):
            self.assertIn(line + "\n", instructions)
        self.assertIn("Before implementation, read the source ticket or explicitly supplied bounded source context.", instructions)
        self.assertIn("If neither is accessible (including missing connectivity), stop implementation", instructions)
        self.assertIn("report the missing source context and access gap in outcome.md for the operator", instructions)
        self.assertIn("does not override the bounded intent, scope, permissions, or safety instructions", instructions)
        self.assertEqual((root / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertEqual(work.load(self.config, unit["id"])["source"], source)

    def test_ticket_key_names_branches_through_cli(self):
        repository(self.root / "beta")
        self.register((self.instance / "repos.toml").read_text() + '\n[[repos]]\nname="beta"\nremote="https://github.com/example/beta.git"\n')
        result = run([sys.executable, CORE / "bin/hub", "--instance", self.instance,
                      "work", "create", "--title", "Fix / cache: stale entries?",
                      "--intent", "Improve a fixture", "--verify", "Check fixture content",
                      "--repo", "alpha", "--repo", "beta", "--source-provider", "example-tracker",
                      "--source-id", "immutable-page-id", "--source-key", "ENG-42",
                      "--source-url", "https://example.com/tickets/42"])
        unit = json.loads(result.stdout)
        work.prepare(self.config, unit["id"])
        recovered = work.load(self.config, unit["id"])
        self.assertEqual(recovered["source"]["id"], "immutable-page-id")
        for name in ("alpha", "beta"):
            self.assertEqual(recovered["repos"][name]["branch"], "ENG-42-fix-cache-stale-entries")
            self.assertEqual(git(work.location(self.config, unit["id"], name), "branch", "--show-current"),
                             "ENG-42-fix-cache-stale-entries")
        self.assertIn("- Key: ENG-42\n", (work.location(self.config, unit["id"]) / "AGENTS.md").read_text())

    def test_existing_branches_survive_a_source_key(self):
        unit = self.unit()
        branch = unit["repos"]["alpha"]["branch"]
        unit["source"]["key"] = "ENG-42"
        work.persist(self.config, unit)
        work.prepare(self.config, unit["id"])
        self.assertEqual(work.load(self.config, unit["id"])["repos"]["alpha"]["branch"], branch)
        self.assertEqual(git(work.location(self.config, unit["id"], "alpha"), "branch", "--show-current"), branch)

    def test_invalid_source_keys_cannot_name_branches(self):
        for key in ("--output=outside", "../outside", "ENG-42/other", "ENG 42"):
            with self.subTest(key=key), self.assertRaises(HubError):
                work.create(self.config, "Task", "Improve a fixture", ["alpha"],
                            "Check fixture content", source={"key": key})

    def test_execution_records_are_ignored_without_duplicate_handoffs(self):
        unit = self.unit()
        root = work.record_path(self.config, unit["id"]).parent
        write(work.location(self.config, unit["id"]) / "outcome.md", "Reviewed fixture result")
        work.report(self.config, unit["id"], "Reviewed fixture", "Operator checked fixture")
        self.assertEqual({p.name for p in root.iterdir()}, {"unit.json"})
        self.assertEqual(git(self.instance, "check-ignore", "work/" + unit["id"] + "/unit.json"),
                         "work/" + unit["id"] + "/unit.json")
        git(self.instance, "add", "--all")
        self.assertEqual(git(self.instance, "ls-files", "work", ".hub"), "")
        self.assertEqual(work.load(Config(self.instance), unit["id"])["status"], "review")

    def test_worker_partial_sources_require_context(self):
        unit = self.unit([])
        for source in ({"url": "https://example.com/tickets/42"}, {"id": "example-42"}, {"key": "ENG-42"},
                       {"provider": "example-tracker"},
                       {"provider": "manual", "url": "https://example.com/tickets/42"},
                       {"provider": None, "id": "example-42", "url": None}):
            with self.subTest(source=source):
                unit["source"] = source
                instructions = work.worker_instructions(self.config, unit)
                self.assertIn("Before implementation, read the source ticket", instructions)
                for field, label in (("provider", "Provider"), ("id", "ID"), ("url", "URL")):
                    if source.get(field):
                        self.assertIn(f"- {label}: {source[field]}\n", instructions)
                    else:
                        self.assertNotIn(f"- {label}:", instructions)

    def test_worker_manual_and_missing_source_compatibility(self):
        unit = self.unit([])
        self.assertEqual(unit["source"], {"provider": "manual"})
        for source in ({"provider": "manual"}, {}, None,
                       {"provider": None, "id": None, "url": None}):
            with self.subTest(source=source):
                unit["source"] = source
                instructions = work.worker_instructions(self.config, unit)
                self.assertNotIn("Before implementation, read the source ticket", instructions)
                self.assertNotIn("stop implementation", instructions)
                self.assertIn(unit["intent"], instructions)
        del unit["source"]
        self.assertNotIn("## Source", work.worker_instructions(self.config, unit))

    def test_multi_repository_worktree(self):
        repository(self.root / "beta")
        self.register((self.instance / "repos.toml").read_text() + '\n[[repos]]\nname="beta"\nremote="https://github.com/example/beta.git"\n')
        unit = self.unit(["alpha", "beta"])
        self.assertTrue(work.location(self.config, unit["id"], "beta").is_dir())

    def test_non_code_work(self):
        unit = self.unit([])
        root = work.location(self.config, unit["id"])
        write(root / "report.md", "artifact")
        self.assertEqual(agents.plan(self.config, "worker", unit["id"])["cwd"], str(root))

    def test_cleanup_dry_run_then_apply(self):
        unit = self.unit()
        path = work.location(self.config, unit["id"], "alpha")
        self.assertFalse(work.cleanup(self.config, unit["id"])["applied"])
        self.assertTrue(path.exists())
        work.cleanup(self.config, unit["id"], True)
        self.assertFalse(path.exists())
        self.assertTrue(work.record_path(self.config, unit["id"]).exists())
        self.assertTrue(git(self.repo, "show-ref", "refs/heads/" + unit["repos"]["alpha"]["branch"]))

    def test_cleanup_refuses_dirty(self):
        unit = self.unit()
        write(work.location(self.config, unit["id"], "alpha") / "example.txt", "dirty")
        with self.assertRaises(HubError):
            work.cleanup(self.config, unit["id"], True)

    def test_cleanup_refuses_untracked(self):
        unit = self.unit()
        write(work.location(self.config, unit["id"], "alpha") / "new.txt", "untracked")
        with self.assertRaises(HubError):
            work.cleanup(self.config, unit["id"], True)

    def test_cleanup_refuses_ignored(self):
        write(self.repo / ".gitignore", "ignored/\n")
        commit(self.repo)
        unit = self.unit()
        write(work.location(self.config, unit["id"], "alpha") / "ignored/cache", "valuable")
        with self.assertRaises(HubError):
            work.cleanup(self.config, unit["id"], True)

    def test_cleanup_refuses_extra_commits(self):
        unit = self.unit()
        p = work.location(self.config, unit["id"], "alpha")
        write(p / "example.txt", "committed")
        commit(p)
        with self.assertRaises(HubError):
            work.cleanup(self.config, unit["id"], True)

    def test_cleanup_refuses_locally_merged_but_unpushed(self):
        unit = self.unit()
        p = work.location(self.config, unit["id"], "alpha")
        write(p / "example.txt", "committed")
        commit(p)
        git(self.repo, "merge", "--ff-only", unit["repos"]["alpha"]["branch"])
        with self.assertRaises(HubError):
            work.cleanup(self.config, unit["id"], True)

    def test_cleanup_refuses_active_and_interrupted(self):
        unit = self.unit()
        for state in ["running", "interrupted"]:
            unit["sessions"] = [{"id": "session", "status": state}]
            work.persist(self.config, unit)
            with self.assertRaises(HubError):
                work.cleanup(self.config, unit["id"], True)
        work.release(self.config, unit["id"], "session")
        work.cleanup(self.config, unit["id"], True)

    def test_branch_change_detected(self):
        unit = self.unit()
        p = work.location(self.config, unit["id"], "alpha")
        git(p, "checkout", "-b", "unexpected")
        with self.assertRaises(HubError):
            agents.plan(self.config, "worker", unit["id"])

    def test_guard_blocks_default_branch(self):
        with self.assertRaises(HubError):
            repos.guard(self.repo, "main")

    def test_hooks_block_commit_and_protected_push(self):
        repos.install_guard(self.config, "alpha")
        write(self.repo / "example.txt", "change")
        git(self.repo, "add", "example.txt")
        r = run(["git", "-C", self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "blocked"], check=False)
        self.assertNotEqual(r.returncode, 0)
        git(self.repo, "checkout", "-b", "feature")
        hook = self.repo / ".git/hooks/pre-push"
        r = subprocess.run([str(hook)], cwd=self.repo, input="refs/heads/feature " + "a" * 40 + " refs/heads/main " + "b" * 40 + "\n", text=True, capture_output=True)
        self.assertNotEqual(r.returncode, 0)

    def test_existing_hook_not_overwritten(self):
        hook = self.repo / ".git/hooks/pre-commit"
        write(hook, "keep me")
        with self.assertRaises(HubError):
            repos.install_guard(self.config, "alpha")
        self.assertEqual(hook.read_text(), "keep me")

    def test_worker_scope_and_no_escalation(self):
        unit = self.unit()
        args = agents.plan(self.config, "worker", unit["id"])["command"]
        self.assertTrue(any('filesystem=' in arg and '"write"' in arg for arg in args))
        self.assertIn("never", args)
        self.assertNotIn("--add-dir", args)
        self.assertNotIn("danger-full-access", args)

    def test_orchestrator_read_only(self):
        self.assertIn("read-only", agents.plan(self.config, "orchestrator")["permissions"])

    def test_claude_not_claimed_implemented(self):
        self.config.runtime = "claude"
        with self.assertRaises(HubError):
            agents.plan(self.config, "orchestrator")

    def test_session_and_handoff_survive_agent_exit(self):
        unit = self.unit()
        with patch("agent_hub.agents.sandbox_probe", return_value={"passed": True}), patch("agent_hub.agents.execute", return_value=subprocess.CompletedProcess([], 0)):
            agents.launch(self.config, "worker", unit["id"], noninteractive=True)
        recovered = work.load(Config(self.instance), unit["id"])
        self.assertEqual(recovered["sessions"][0]["status"], "finished")
        report = work.report(self.config, unit["id"], "Completed fixture investigation", "Operator ran content check")
        self.assertEqual(report["status"], "review")
        self.assertIn("operator-reported", report["verification"][0]["kind"])

    def test_failed_agent_is_interrupted(self):
        unit = self.unit()
        with patch("agent_hub.agents.sandbox_probe", return_value={"passed": True}), patch("agent_hub.agents.execute", return_value=subprocess.CompletedProcess([], 7)):
            agents.launch(self.config, "worker", unit["id"], noninteractive=True)
        self.assertEqual(work.load(self.config, unit["id"])["sessions"][0]["status"], "interrupted")

    def test_report_refuses_external_symlink(self):
        unit = self.unit()
        secret = self.root / "private.txt"
        write(secret, "private")
        (work.location(self.config, unit["id"]) / "outcome.md").symlink_to(secret)
        with self.assertRaises(HubError):
            work.report(self.config, unit["id"], "summary")

    def test_failed_sandbox_probe_prevents_agent_execution(self):
        unit = self.unit()
        with patch("agent_hub.agents.sandbox_probe", return_value={"passed": False}), patch("agent_hub.agents.execute") as execute:
            with self.assertRaises(HubError):
                agents.launch(self.config, "worker", unit["id"], noninteractive=True)
            execute.assert_not_called()

    def test_legacy_runtime_config_refused_without_rewriting(self):
        native_home = self.root / "runtime-home"
        native_home.mkdir()
        content = 'sandbox_mode="danger-full-access"\n'
        write(native_home / "config.toml", content)
        with patch.dict(os.environ, {"CODEX_HOME": str(native_home)}):
            with self.assertRaises(HubError):
                agents.check_native_config(self.instance)
        self.assertEqual((native_home / "config.toml").read_text(), content)

    def test_noninteractive_logs_discard_provider_payloads(self):
        unit = self.unit()
        secret = "ghp_" + "z" * 40
        output = json.dumps({"type": "item.completed", "item": {"text": secret}}) + "\n"
        with patch("agent_hub.agents.sandbox_probe", return_value={"passed": True}), patch("agent_hub.agents.execute", return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=secret)):
            result = agents.launch(self.config, "worker", unit["id"], noninteractive=True)
        log = Path(result["log"]).read_text()
        self.assertNotIn(secret, log)
        self.assertIn("item.completed", log)
        self.assertNotIn("item\"", log)

    def test_outcome_import_refuses_credentials(self):
        unit = self.unit()
        write(work.location(self.config, unit["id"]) / "outcome.md", "ghp_" + "z" * 40)
        with self.assertRaises(HubError):
            work.report(self.config, unit["id"], "summary")
        self.assertFalse((work.record_path(self.config, unit["id"]).parent / "worker-outcome.md").exists())

    def test_work_metadata_cannot_inject_git_arguments(self):
        unit = self.unit()
        unit["repos"]["alpha"]["base"] = "--output=/outside"
        work.persist(self.config, unit)
        with self.assertRaises(HubError):
            work.status(self.config, unit["id"])

    def test_worktree_directory_symlink_escape_refused(self):
        unit = work.create(self.config, "Test", "Test symlink handling", ["alpha"], "No outside writes")
        target = self.root / "outside"
        target.mkdir()
        parent = self.instance / ".hub/worktrees"
        parent.mkdir()
        (parent / unit["id"]).symlink_to(target, target_is_directory=True)
        with self.assertRaises(HubError):
            work.prepare(self.config, unit["id"])
        self.assertEqual(list(target.iterdir()), [])

    def test_cleanup_allows_commits_proven_merged_in_tracked_origin(self):
        unit = self.unit()
        p = work.location(self.config, unit["id"], "alpha")
        write(p / "example.txt", "reviewed change")
        commit(p)
        git(self.repo, "merge", "--ff-only", unit["repos"]["alpha"]["branch"])
        git(self.repo, "update-ref", "refs/remotes/origin/main", git(self.repo, "rev-parse", "HEAD"))
        self.assertTrue(work.cleanup(self.config, unit["id"], True)["applied"])

    def test_adoption_refuses_stale_lock_plan(self):
        changed = dict(self.config.lock, version="concurrently changed")
        save(self.instance / "core.lock", changed)
        with self.assertRaises(HubError):
            evolution.adopt(self.config, str(self.source), self.first, apply=True)
        self.assertEqual(read_json(self.instance / "core.lock"), changed)

    def test_reconciliation_all_four_classifications(self):
        inventory = self.root / "inventory.toml"
        write(inventory, '[[capabilities]]\nname="worktrees"\n\n[[capabilities]]\nname="private-policy"\n\n[[capabilities]]\nname="novel"\ngeneralizable=true\n\n[[capabilities]]\nname="bootstrap"\nobsolete=true\n')
        report = evolution.reconcile(self.config, str(inventory))
        self.assertEqual({r["classification"] for r in report["differences"]}, {"Adopt", "Preserve", "Promote candidate", "Retire"})

    def test_secret_redaction_preserves_json_structure(self):
        from agent_hub.common import sanitize
        secret = "ghp_" + "z" * 40
        result = sanitize({"command": ["tool", "token=" + secret]})
        encoded = json.dumps(result)
        self.assertNotIn(secret, encoded)
        self.assertEqual(json.loads(encoded), result)

    def test_work_id_path_traversal(self):
        with self.assertRaises(HubError):
            work.load(self.config, "../../outside")

    def test_core_self_reference_independent_runtime(self):
        editable = self.root / "editable-core"
        run(["git", "clone", "--", self.source, editable])
        self.register('[[repos]]\nname="editable-core"\nremote=' + toml_string(self.source) + '\nvisible=false\n')
        unit = self.unit(["editable-core"])
        p = work.location(self.config, unit["id"], "editable-core")
        write(p / "improvement.md", "independent improvement")
        active = self.instance / ".hub/cores" / self.first
        self.assertFalse((active / "improvement.md").exists())
        self.assertTrue(repos.doctor(self.config)["ready"])

    def test_adopt_and_rollback_preserve_configuration(self):
        candidate = self.root / "candidate"
        run(["git", "clone", "--", self.source, candidate])
        write(candidate / "change.md", "public improvement")
        commit(candidate, "Improve public fixture")
        before = (self.instance / "hub.toml").read_bytes()
        plan = evolution.adopt(self.config, str(candidate), "HEAD")
        self.assertTrue(plan["compatible"])
        self.assertEqual(Config(self.instance).lock["commit"], self.first)
        result = evolution.adopt(self.config, str(candidate), "HEAD", apply=True)
        self.assertTrue(result["applied"])
        new_config = Config(self.instance)
        self.assertNotEqual(new_config.lock["commit"], self.first)
        evolution.rollback(new_config)
        self.assertEqual(Config(self.instance).lock["commit"], self.first)
        self.assertEqual(before, (self.instance / "hub.toml").read_bytes())

    def test_adopt_failed_tests_keeps_lock(self):
        candidate = self.root / "candidate"
        run(["git", "clone", "--", self.source, candidate])
        write(candidate / "tests/test_failure.py", "import unittest\nclass Fail(unittest.TestCase):\n def test_fail(self): self.fail('candidate failure')\n")
        commit(candidate)
        with self.assertRaises(HubError):
            evolution.adopt(self.config, str(candidate), "HEAD", apply=True)
        self.assertEqual(Config(self.instance).lock["commit"], self.first)

    def test_adopt_incompatible_schema_keeps_lock(self):
        candidate = self.root / "candidate"
        run(["git", "clone", "--", self.source, candidate])
        write(candidate / "templates/instance/hub.toml", 'schema_version=99\n')
        commit(candidate)
        self.assertFalse(evolution.adopt(self.config, str(candidate), "HEAD")["compatible"])
        with self.assertRaises(HubError):
            evolution.adopt(self.config, str(candidate), "HEAD", apply=True)

    def test_dirty_installed_core_detected(self):
        write(self.instance / ".hub/cores" / self.first / "unwanted.txt", "dirty")
        self.assertFalse(repos.doctor(self.config)["ready"])
        with self.assertRaises(HubError):
            evolution.install(self.instance, str(self.source), self.first)

    def test_reconciliation_read_only(self):
        inventory = self.root / "inventory.toml"
        write(inventory, '[[capabilities]]\nname="worktrees"\ndescription="existing"\n\n[[capabilities]]\nname="novel"\ngeneralizable=true\nownership="organization"\n')
        before = git(self.instance, "status", "--porcelain")
        report = evolution.reconcile(self.config, str(inventory))
        self.assertTrue(report["read_only"])
        self.assertEqual(report["differences"][1]["classification"], "Promote candidate")
        self.assertEqual(before, git(self.instance, "status", "--porcelain"))

    def test_promotion_blocked_without_rights(self):
        proposal = evolution.promote(self.config, "General problem", "General requirement", "organization")
        self.assertIn("blocked", proposal["status"])
        self.assertFalse(proposal["copied_material"])

    def test_services_opt_in_and_missing_environment(self):
        self.config.resources = [{"name": "dev", "kind": "service", "repo": "alpha",
                                  "command": [sys.executable, "-c", "print('dev')"], "environment": ["HUB_TEST_ABSENT"]}]
        self.assertIn("HUB_TEST_ABSENT", service(self.config, "dev")["missing_environment"])
        with self.assertRaises(HubError):
            service(self.config, "dev", execute=True, allow_sensitive=True)

    def test_sensitive_service_requires_extra_opt_in(self):
        self.config.resources = [{"name": "dev", "kind": "service", "command": ["echo", "test"]}]
        with self.assertRaises(HubError):
            service(self.config, "dev", execute=True)

    def test_secret_scanning_withholds_values(self):
        secret = "ghp_" + "x" * 40
        write(self.repo / "accidental.txt", secret)
        result = security.scan(self.repo)
        self.assertFalse(result["passed"])
        self.assertNotIn(secret, json.dumps(result))

    def test_secret_scanning_detects_forced_private_file(self):
        write(self.repo / "local.toml", "private=true")
        git(self.repo, "add", "local.toml")
        self.assertFalse(security.scan(self.repo, staged=True)["passed"])

    def test_cli_invalid_config_returns_nonzero_without_traceback(self):
        r = run([sys.executable, CORE / "bin/hub", "--instance", self.root / "missing", "doctor"], check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
