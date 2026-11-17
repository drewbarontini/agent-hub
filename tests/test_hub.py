from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_hub import agents, context, evolution, prune, repos, security, work
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

    def test_instance_launcher_works_from_session_path(self):
        launcher = self.instance / ".hub/bin/hub"
        self.assertTrue(launcher.is_symlink())
        env = dict(os.environ)
        env["PATH"] = str(launcher.parent) + os.pathsep + env.get("PATH", "")
        if not shutil.which("python3", path=env["PATH"]):
            self.skipTest("No python3 available for env shebang")
        check = subprocess.run(
            ["python3", "-c", "import sys; sys.exit(sys.version_info < (3, 11))"],
            cwd=self.instance, env=env, capture_output=True, text=True)
        if check.returncode != 0:
            self.skipTest("python3 on PATH is older than 3.11")
        result = subprocess.run(
            ["hub", "config-check"], cwd=self.instance, env=env,
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])
        self.assertEqual(json.loads(result.stdout)["repositories"], 1)

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

    def test_context_index_reads_registry_without_fetching_external_sources(self):
        with (self.instance / "hub.toml").open("a") as stream:
            stream.write('\n[[resources]]\nname="board"\nkind="work"\nlocation="https://example.org/tasks"\npurpose="Current decisions"\n')
            stream.write('\n[[resources]]\nname="notes"\nkind="context"\npath="../missing-notes"\npurpose="Learning and docs"\n')
        self.config = Config(self.instance)
        before = git(self.repo, "status", "--porcelain", "--untracked-files=all")
        summary = context.catalog(self.config)
        self.assertEqual(summary["board"][0]["name"], "board")
        self.assertEqual(summary["knowledge"][0]["name"], "notes")
        self.assertIn("unsupported", summary["board"][0]["connectivity"])
        result = context.write_index(self.config)
        text = Path(result["index"]).read_text()
        self.assertIn("Board", text)
        self.assertIn("Knowledge (Memory / Docs)", text)
        self.assertIn("requires provider authentication", text)
        self.assertIn("local path missing", text)
        self.assertIn("https://example.org/tasks", text)
        self.assertTrue((self.instance / ".hub/context/resources.md").exists())
        self.assertEqual(before, git(self.repo, "status", "--porcelain", "--untracked-files=all"))
        self.assertFalse((self.instance / "CONTEXT.md").exists())
        with self.assertRaises(HubError):
            context.catalog(self.config, "../private")

    def test_context_index_workspace_and_progressive_pages(self):
        # Test stable pagination without multiplying real repositories.
        base = dict(self.config.repos["alpha"])
        self.config.repos = {
            "alpha-" + str(i): dict(base, name="alpha-" + str(i), description="Repo " + str(i))
            for i in range(27)
        }
        pages = context.render(self.config)
        self.assertIn("27 of 27", pages["CONTEXT.md"])
        self.assertIn("context/repositories-2.md", pages)
        self.assertLess(len(pages["CONTEXT.md"].splitlines()), 65)
        saved = context.write_index(self.config)
        self.assertEqual(saved["generated_files"], len(pages))
        self.assertTrue((self.instance / ".hub/context/repositories-2.md").is_file())
        result = repos.workspace(self.config)
        self.assertTrue(Path(result["context_index"]).is_file())
        self.assertIn(".hub/CONTEXT.md", str(Path(result["context_index"])))
        self.assertFalse((self.instance / "context").exists())

    def test_registered_capability_inventory_exact_overlap_and_scope(self):
        beta = repository(self.root / "beta")
        write(self.repo / "AGENTS.md", "COMMON GUIDANCE\n")
        write(beta / "AGENTS.md", "COMMON GUIDANCE\n")
        write(self.repo / ".agents/skills/local/SKILL.md", "local skill\n")
        write(beta / ".agents/skills/local/SKILL.md", "different skill\n")
        write(beta / "private/secret.txt", "NEVER READ THIS\n")
        self.register(
            '[[repos]]\nname="alpha"\nremote="https://github.com/example/alpha.git"\n'
            '[[repos]]\nname="beta"\nremote="https://github.com/example/beta.git"\n'
        )
        before = (git(self.repo, "status", "--porcelain"), git(beta, "status", "--porcelain"))
        rows = context.inventory(self.config, ["alpha", "beta"])
        agent_rows = [x for x in rows["items"] if x["path"] == "AGENTS.md"]
        self.assertEqual(len(agent_rows), 2)
        self.assertTrue(all(x["classification"] == "exact duplicate" for x in agent_rows))
        skill_rows = [x for x in rows["items"] if x["path"].endswith("SKILL.md")]
        self.assertTrue(all(x["classification"] == "name overlap (review only)" for x in skill_rows))
        self.assertNotIn("NEVER READ THIS", str(rows))
        self.assertNotIn("COMMON GUIDANCE", str(rows))
        self.assertNotIn("_sha", str(rows))
        self.assertEqual(before, (git(self.repo, "status", "--porcelain"), git(beta, "status", "--porcelain")))
        self.assertEqual(context.inventory(self.config, ["alpha"])["scope"], ["alpha"])
        with self.assertRaises(HubError):
            context.inventory(self.config, ["not-registered"])

    def test_inventory_skips_symlinks_and_unavailable_repos(self):
        outside = self.root / "outside.md"
        write(outside, "sensitive material\n")
        (self.repo / "AGENTS.md").symlink_to(outside)
        self.register(self.instance.joinpath("repos.toml").read_text() +
                      '[[repos]]\nname="missing"\nremote="https://github.com/example/missing.git"\n')
        report = context.inventory(self.config)
        self.assertFalse(any(x["path"] == "AGENTS.md" for x in report["items"]))
        self.assertEqual(report["unavailable_or_unreadable"][0]["repository"], "missing")
        self.assertNotIn("sensitive material", str(report))

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

    def test_doctor_claude_adapter_has_independent_probe_status(self):
        save(self.instance / ".hub/last-sandbox-probe.json", {
            "passed": True, "exit_code": 0,
            "checks": {"inside_write": True, "outside_and_metadata_blocked": [True]}})
        self.config.runtime = "claude"
        with patch("agent_hub.repos.executable", return_value=sys.executable):
            result = repos.doctor(self.config)
        self.assertTrue(result["ready"])
        self.assertEqual(result["agent_execution"]["runtime"], "claude")
        self.assertTrue(result["agent_execution"]["launch_adapter_implemented"])
        self.assertEqual(result["agent_execution"]["last_sandbox_probe"], {"runtime": "claude", "status": "not-probed"})
        self.assertEqual(result["agent_execution"]["worker_execution"], "unverified")
        save(self.instance / ".hub/last-claude-sandbox-probe.json", {
            "passed": False, "exit_code": 1,
            "checks": {"reason": "No native sandbox"}})
        self.assertEqual(repos.doctor(self.config)["agent_execution"]["last_sandbox_probe"]["status"], "blocked")
        save(self.instance / ".hub/last-claude-sandbox-probe.json", {
            "passed": True, "exit_code": 0,
            "checks": {"inside_write": True, "outside_and_metadata_blocked": [True],
                       "git_metadata_readable": [True]}})
        self.assertEqual(repos.sandbox_probe_status(self.config, "claude"), "passed")
        save(self.instance / ".hub/last-claude-sandbox-probe.json", {
            "passed": True, "exit_code": 0,
            "checks": {"inside_write": True, "outside_and_metadata_blocked": [True],
                       "git_metadata_readable": [False]}})
        self.assertEqual(repos.sandbox_probe_status(self.config, "claude"), "unknown")

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

    def start_cli(self, *args, check=True):
        return run([sys.executable, CORE / "bin/hub", "--instance", self.instance,
                    "work", "start", *args], check=check)

    def start_args(self):
        return ["ENG-42", "--title", "Fix cache", "--intent", "Improve a fixture",
                "--verify", "Check fixture content", "--repo", "alpha",
                "--source-provider", "example-tracker", "--source-id", "immutable-page-id"]

    def test_start_cli_creates_and_resumes_multi_repo_work(self):
        repository(self.root / "beta")
        self.register((self.instance / "repos.toml").read_text() + '\n[[repos]]\nname="beta"\nremote="https://github.com/example/beta.git"\n')
        args = self.start_args() + ["--repo", "beta"]
        first = json.loads(self.start_cli(*args).stdout)
        self.assertFalse(first["reused"])
        self.assertEqual(first["status"], "prepared")
        self.assertEqual(first["key"], "ENG-42")
        self.assertEqual(len(first["next_commands"]), 3)
        for name in ("alpha", "beta"):
            path = work.location(self.config, first["id"], name)
            self.assertEqual(git(path, "branch", "--show-current"), "ENG-42-fix-cache")
        for args in (args, ["ENG-42"], [first["id"]]):
            resumed = json.loads(self.start_cli(*args).stdout)
            self.assertTrue(resumed["reused"])
            self.assertEqual(resumed["id"], first["id"])
        self.assertEqual(len(work.units(self.config)), 1)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")

    def test_start_concurrent_invocations_share_one_execution(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: json.loads(self.start_cli(*self.start_args()).stdout), range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(sorted(r["reused"] for r in results), [False, True])
        self.assertEqual(len(work.units(self.config)), 1)

    def test_start_ignores_unregistered_repositories_in_unrelated_history(self):
        historical = self.unit()
        work.cleanup(self.config, historical["id"], apply=True)
        source = {"provider": "example-tracker", "id": "analysis-page", "key": "ENG-43"}
        active = work.create(self.config, "Analysis", "Reason about a fixture", [],
                             "Review the reasoning", source=source)
        self.register("")
        for args in ([active["id"]], ["ENG-43"],
                     ["--source-provider", source["provider"], "--source-id", source["id"]]):
            with self.subTest(args=args):
                resumed = json.loads(self.start_cli(*args).stdout)
                self.assertEqual(resumed["id"], active["id"])
                self.assertTrue(resumed["reused"])
        self.assertEqual(work.resolve(self.config, "ENG-43"), active["id"])
        created = json.loads(self.start_cli("--title", "New analysis", "--intent", "Reason about another fixture",
                                           "--verify", "Review the reasoning", "--no-repos").stdout)
        self.assertFalse(created["reused"])
        self.assertEqual(created["status"], "prepared")
        self.assertEqual(created["repos"], {})

    def test_selected_execution_still_requires_registered_repositories(self):
        selected = json.loads(self.start_cli(*self.start_args()).stdout)
        self.register("")
        record = work.record_path(self.config, selected["id"]).read_bytes()
        for reference in (selected["id"], "ENG-42"):
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(HubError, "Unregistered repository: alpha"):
                    work.resolve(self.config, reference)
                result = self.start_cli(reference, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unregistered repository: alpha", result.stderr)
        result = self.start_cli("--source-provider", "example-tracker", "--source-id", "immutable-page-id",
                                check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unregistered repository: alpha", result.stderr)
        self.assertEqual(work.record_path(self.config, selected["id"]).read_bytes(), record)

    def test_start_reuses_immutable_identity_without_renaming_branch(self):
        first = json.loads(self.start_cli(*self.start_args()).stdout)
        resumed = work.start(self.config, "NEW-42", source={"provider": "example-tracker",
                             "id": "immutable-page-id", "key": "NEW-42"})
        self.assertEqual(resumed["id"], first["id"])
        self.assertEqual(resumed["key"], "ENG-42")
        self.assertEqual(resumed["repos"], first["repos"])
        self.assertEqual(len(work.units(self.config)), 1)

    def test_start_refuses_changed_identity_scope_or_requirements(self):
        first = json.loads(self.start_cli(*self.start_args()).stdout)
        record = work.record_path(self.config, first["id"]).read_bytes()
        for fields in ({"source": {"provider": "example-tracker", "id": "other-page"}},
                       {"source": {"provider": "other-tracker", "id": "immutable-page-id"}},
                       {"names": []}, {"resource_names": ["unknown"]},
                       {"title": "Changed title"}, {"intent": "Changed intent"},
                       {"verification": "Changed verification"}):
            with self.subTest(fields=fields), self.assertRaises(HubError):
                work.start(self.config, "ENG-42", **fields)
        self.assertEqual(work.record_path(self.config, first["id"]).read_bytes(), record)

    def test_start_first_run_requires_explicit_scope_and_resolved_source(self):
        for args in (["ENG-42"], ["ENG-42", "--title", "Task", "--intent", "Intent", "--verify", "Check"],
                     ["--title", "Task", "--intent", "Intent", "--verify", "Check"],
                     ["W-doesnotexist"], ["../outside"]):
            with self.subTest(args=args):
                result = self.start_cli(*args, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(work.units(self.config), [])
        result = json.loads(self.start_cli("--title", "Analysis", "--intent", "Reason about a fixture",
                                          "--verify", "Review the reasoning", "--no-repos").stdout)
        self.assertEqual(result["repos"], {})
        self.assertIsNone(result["key"])

    def test_start_refuses_ambiguous_source_and_resolves_legacy_ids(self):
        first = json.loads(self.start_cli(*self.start_args()).stdout)
        duplicate = work.create(self.config, "Other execution", "Improve a fixture", [], "Check fixture content",
                                source={"provider": "example-tracker", "id": "immutable-page-id", "key": "ENG-42"})
        with self.assertRaises(HubError):
            work.resolve(self.config, "ENG-42")
        with self.assertRaises(HubError):
            work.start(self.config, "ENG-42")
        with self.assertRaises(HubError):
            work.start(self.config, source={"provider": "example-tracker", "id": "immutable-page-id"})
        for unit in (first, duplicate):
            self.assertEqual(work.resolve(self.config, unit["id"]), unit["id"])
            self.assertEqual(work.start(self.config, unit["id"])["id"], unit["id"])

    def test_start_blocks_live_interrupted_cleaned_and_wrong_branch_work(self):
        result = json.loads(self.start_cli(*self.start_args()).stdout)
        unit = work.load(self.config, result["id"])
        for status in ("running", "interrupted"):
            unit["sessions"] = [{"id": "fixture-session", "status": status}]
            work.persist(self.config, unit)
            with self.subTest(status=status), self.assertRaises(HubError):
                work.start(self.config, "ENG-42")
        unit["sessions"] = []
        unit["status"] = "cleaned"
        work.persist(self.config, unit)
        with self.assertRaises(HubError):
            work.start(self.config, "ENG-42")
        unit["status"] = "prepared"
        work.persist(self.config, unit)
        git(work.location(self.config, unit["id"], "alpha"), "checkout", "-b", "unexpected")
        with self.assertRaises(HubError):
            work.start(self.config, "ENG-42")

    def test_start_resumes_review_without_losing_state_or_changes(self):
        result = json.loads(self.start_cli(*self.start_args()).stdout)
        path = work.location(self.config, result["id"], "alpha")
        write(path / "example.txt", "change under review\n")
        work.report(self.config, result["id"], "Review this fixture")
        resumed = work.start(self.config, "ENG-42")
        self.assertEqual(resumed["status"], "review")
        self.assertEqual((path / "example.txt").read_text(), "change under review\n")
        self.assertEqual(work.load(self.config, result["id"])["summary"], "Review this fixture")

    def test_source_keys_work_across_cli_lifecycle_and_agent_plans(self):
        from agent_hub.cli import dispatch, parser
        result = json.loads(self.start_cli(*self.start_args()).stdout)
        prefix = ["--instance", str(self.instance)]
        for args in (["work", "prepare", "ENG-42"], ["work", "status", "ENG-42"],
                     ["work", "cleanup", "ENG-42"], ["agent", "worker", "ENG-42"]):
            output = dispatch(parser().parse_args(prefix + args))
            self.assertEqual((output[0] if isinstance(output, list) else output)["id"], result["id"])
        with patch.object(agents, "sandbox_probe", return_value={"passed": True}) as probe:
            dispatch(parser().parse_args(prefix + ["sandbox-check", "ENG-42"]))
            self.assertEqual(probe.call_args.args[1], result["id"])
        output = dispatch(parser().parse_args(prefix + ["work", "report", "ENG-42", "--summary", "Reviewed"]))
        self.assertEqual(output["status"], "review")
        output["sessions"] = [{"id": "fixture-session", "status": "interrupted"}]
        work.persist(self.config, output)
        released = dispatch(parser().parse_args(prefix + ["work", "release", "ENG-42", "--session",
                                                         "fixture-session", "--ack-session-ended"]))
        self.assertEqual(released["id"], result["id"])
        self.assertEqual(work.start(self.config, "ENG-42")["status"], "review")

    def test_start_retains_recoverable_record_after_partial_preparation(self):
        original = work.run
        def fail_add(args, **kwargs):
            if "worktree" in args and "add" in args:
                raise HubError("Fixture preparation failure")
            return original(args, **kwargs)
        with patch.object(work, "run", side_effect=fail_add), self.assertRaises(HubError):
            work.start(self.config, "ENG-42", title="Fix cache", intent="Improve a fixture",
                       names=["alpha"], verification="Check fixture content",
                       source={"provider": "example-tracker", "id": "immutable-page-id"})
        unit, = work.units(self.config)
        self.assertEqual(unit["status"], "planned")
        self.assertEqual(work.start(self.config, "ENG-42")["id"], unit["id"])

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

    def cleanup_fixture(self, squash=False):
        origin = self.root / "origin.git"
        run(["git", "init", "--bare", origin])
        # Keep the registered GitHub identity while all Git traffic stays local.
        git(self.repo, "config", "url." + origin.as_uri() + ".insteadOf", "https://github.com/example/alpha.git")
        git(self.repo, "push", "origin", "main")
        git(self.repo, "fetch", "origin")
        unit = self.unit()
        path = work.location(self.config, unit["id"], "alpha")
        write(path / "example.txt", "fixture change\n")
        commit(path, "task change")
        head = git(path, "rev-parse", "HEAD")
        if squash:
            git(self.repo, "merge", "--squash", unit["repos"]["alpha"]["branch"])
            commit(self.repo, "squashed task")
        else:
            git(self.repo, "merge", "--ff-only", unit["repos"]["alpha"]["branch"])
        merged = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "push", "origin", "main")
        git(self.repo, "fetch", "origin")
        unit = work.report(self.config, unit["id"], "Reviewed fixture")
        pr = {"number": 42, "state": "closed", "merged_at": "2026-01-01T00:00:00Z",
              "merge_commit_sha": merged,
              "head": {"ref": unit["repos"]["alpha"]["branch"], "sha": head,
                       "repo": {"full_name": "example/alpha"}},
              "base": {"ref": "main", "repo": {"full_name": "example/alpha"}}}
        return unit, path, pr

    def github_fixture(self, prs, code=0, pages=None):
        self.config.data.setdefault("tools", {})["gh"] = sys.executable
        original = prune.run
        def respond(args, **kwargs):
            if str(args[0]) == sys.executable and args[1] == "api":
                self.assertIn("GET", args)
                self.assertIn("--paginate", args)
                self.assertIn("--slurp", args)
                return subprocess.CompletedProcess(args, code, json.dumps([prs] if pages is None else pages), "provider details withheld")
            return original(args, **kwargs)
        return patch.object(prune, "run", side_effect=respond)

    def test_prune_preview_is_read_only_and_apply_is_explicit(self):
        unit, path, _ = self.cleanup_fixture()
        before = work.record_path(self.config, unit["id"]).read_bytes()
        refs = git(self.repo, "show-ref")
        row, = prune.prune(self.config, unit["id"], delete_branches=True)["work"]
        self.assertEqual(row["state"], "eligible")
        self.assertTrue(row["repos"][0]["delete_branch"])
        self.assertTrue(path.exists())
        self.assertEqual(git(self.repo, "show-ref"), refs)
        self.assertEqual(work.record_path(self.config, unit["id"]).read_bytes(), before)
        result = run([sys.executable, CORE / "bin/hub", "--instance", self.instance,
                      "work", "prune", unit["id"], "--delete-branches", "--apply"])
        row, = json.loads(result.stdout)["work"]
        self.assertEqual(row["state"], "cleaned")
        self.assertEqual(row["removed_worktrees"], ["alpha"])
        self.assertEqual(row["deleted_branches"], ["alpha"])
        self.assertFalse(path.exists())
        self.assertIsNone(prune.branch_head(self.config.repo("alpha"), unit["repos"]["alpha"]["branch"]))
        self.assertEqual(work.load(self.config, unit["id"])["status"], "cleaned")
        self.assertTrue(work.location(self.config, unit["id"]).exists())

    def test_prune_preview_does_not_refresh_git_indexes(self):
        unit, path, _ = self.cleanup_fixture()
        indexes = {}
        for checkout in (self.repo, path):
            git(checkout, "status", "--porcelain")
            index = Path(git(checkout, "rev-parse", "--path-format=absolute", "--git-path", "index"))
            indexes[index] = index.read_bytes()
            tracked = checkout / "example.txt"
            stat = tracked.stat()
            os.utime(tracked, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        row, = prune.prune(self.config, unit["id"], delete_branches=True)["work"]
        self.assertEqual(row["state"], "eligible")
        for index, before in indexes.items():
            self.assertEqual(index.read_bytes(), before, f"Preview refreshed {index}")

    def test_prune_unknown_execution_returns_cli_error_without_changes(self):
        unit, path, _ = self.cleanup_fixture()
        before = work.record_path(self.config, unit["id"]).read_bytes()
        refs = git(self.repo, "show-ref")
        for reference in ("W-doesnotexist", ""):
            with self.subTest(reference=reference):
                result = run([sys.executable, CORE / "bin/hub", "--instance", self.instance,
                              "work", "prune", reference, "--apply", "--delete-branches"], check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("error", json.loads(result.stdout or result.stderr))
                self.assertTrue(path.exists())
                self.assertEqual(git(self.repo, "show-ref"), refs)
                self.assertEqual(work.record_path(self.config, unit["id"]).read_bytes(), before)

    def test_prune_default_retains_branches_and_later_deletes_eligible_branch(self):
        unit, path, _ = self.cleanup_fixture()
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertEqual(row["deleted_branches"], [])
        self.assertFalse(path.exists())
        self.assertIsNotNone(prune.branch_head(self.config.repo("alpha"), unit["repos"]["alpha"]["branch"]))
        row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)["work"]
        self.assertEqual(row["deleted_branches"], ["alpha"])
        self.assertEqual(prune.prune(self.config, unit["id"])["work"][0]["state"], "kept")

    def test_prune_recognizes_squash_merge_and_retains_original_branch(self):
        unit, path, pr = self.cleanup_fixture(squash=True)
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertTrue(path.exists())
        with self.github_fixture([pr]):
            row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True, github=True)["work"]
        self.assertEqual(row["state"], "cleaned")
        self.assertEqual(row["repos"][0]["merge"], "pr-evidence")
        self.assertEqual(row["deleted_branches"], [])
        self.assertIn("original commits", row["repos"][0]["branch_reason"])
        self.assertEqual(prune.branch_head(self.config.repo("alpha"), unit["repos"]["alpha"]["branch"]), pr["head"]["sha"])
        self.assertFalse(path.exists())

    def test_prune_keeps_extra_local_commits_even_when_pr_merged(self):
        unit, path, pr = self.cleanup_fixture()
        write(path / "extra.txt", "additional local work")
        commit(path)
        with self.github_fixture([pr]):
            row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True, github=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertIn("final head", row["reasons"][0])
        self.assertTrue(path.exists())
        self.assertIsNotNone(prune.branch_head(self.config.repo("alpha"), unit["repos"]["alpha"]["branch"]))

    def test_prune_refuses_open_closed_unmerged_and_wrong_base_prs(self):
        unit, path, pr = self.cleanup_fixture()
        for changes in ({"state": "open", "merged_at": None}, {"merged_at": None},
                        {"base": {"ref": "release", "repo": {"full_name": "example/alpha"}}},
                        {"head": dict(pr["head"], repo={"full_name": "other/alpha"})},
                        {"merge_commit_sha": None}, {"merge_commit_sha": "0" * 40},
                        {"head": dict(pr["head"], sha="0" * 40)}):
            with self.subTest(changes=changes), self.github_fixture([dict(pr, **changes)]):
                row, = prune.prune(self.config, unit["id"], apply=True, github=True)["work"]
                self.assertEqual(row["state"], "kept")
                self.assertTrue(path.exists())
        with self.github_fixture([pr, dict(pr, number=43, merged_at=None)]):
            self.assertEqual(prune.prune(self.config, unit["id"], github=True)["work"][0]["state"], "kept")
        with self.github_fixture([], pages=[[pr], [dict(pr, number=43, state="open", merged_at=None)]]):
            self.assertEqual(prune.prune(self.config, unit["id"], github=True)["work"][0]["state"], "kept")

    def test_prune_keeps_work_when_provider_is_missing_unavailable_or_malformed(self):
        unit, path, pr = self.cleanup_fixture()
        with patch.object(prune, "executable", return_value=None):
            row, = prune.prune(self.config, unit["id"], apply=True, github=True)["work"]
            self.assertIn("unavailable", row["reasons"][0])
        for response, code in (([pr], 1), ([], 0), ({"unexpected": "object"}, 0)):
            with self.subTest(response=response, code=code), self.github_fixture(response, code):
                row, = prune.prune(self.config, unit["id"], apply=True, github=True)["work"]
                self.assertEqual(row["state"], "kept")
                self.assertNotIn("provider details", str(row))
                self.assertTrue(path.exists())

    def test_prune_preview_does_not_lazy_fetch_from_a_promisor_remote(self):
        unit, path, pr = self.cleanup_fixture()
        origin = self.root / "origin.git"
        identity = ["-c", "user.name=Hub Test", "-c", "user.email=hub@example.invalid"]
        remote_head = git(origin, *identity, "commit-tree", git(origin, "rev-parse", "main^{tree}"),
                          "-p", pr["head"]["sha"], "-m", "remote-only PR head")
        git(origin, "update-ref", "refs/heads/remote-pr", remote_head)
        git(origin, "config", "uploadpack.allowFilter", "true")
        self.assertNotEqual(run(["git", "-C", self.repo, "cat-file", "-e", remote_head], check=False).returncode, 0)
        git(self.repo, "config", "remote.origin.promisor", "true")
        git(self.repo, "config", "remote.origin.partialclonefilter", "blob:none")
        objects = self.repo / ".git/objects"
        before = {p.relative_to(objects): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in objects.rglob("*") if p.is_file()}
        for promisor in ("true", "false"):
            git(self.repo, "config", "remote.origin.promisor", promisor)
            with self.subTest(promisor=promisor), self.github_fixture([dict(pr, head=dict(pr["head"], sha=remote_head))]):
                row, = prune.prune(self.config, unit["id"], github=True)["work"]
                after = {p.relative_to(objects): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in objects.rglob("*") if p.is_file()}
                self.assertEqual(after, before, "Preview fetched missing objects")
                self.assertEqual(row["state"], "kept")
                self.assertIn("Partial clone", row["reasons"][0])
        self.assertTrue(path.exists())

    def test_prune_refuses_dirty_untracked_ignored_files_and_unreleased_sessions(self):
        unit, path, _ = self.cleanup_fixture()
        for state in ("running", "interrupted"):
            unit["sessions"] = [{"id": "fixture", "status": state}]
            work.persist(self.config, unit)
            self.assertEqual(prune.prune(self.config, unit["id"], apply=True)["work"][0]["state"], "kept")
        unit["sessions"] = []
        work.persist(self.config, unit)
        for file, original in (("example.txt", "fixture change\n"), ("untracked.txt", None)):
            write(path / file, "valuable changes")
            row, = prune.prune(self.config, unit["id"], apply=True)["work"]
            self.assertIn("changed, untracked or ignored", row["reasons"][0])
            if original is None:
                (path / file).unlink()
            else:
                write(path / file, original)
        ignored = self.root / "ignore-rules"
        write(ignored, "ignored/\n")
        git(self.repo, "config", "core.excludesFile", str(ignored))
        write(path / "ignored/cache", "valuable ignored work")
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertTrue((path / "ignored/cache").exists())

    def check_hidden_index_changes(self, flags):
        unit, path, _ = self.cleanup_fixture()
        for flag in flags:
            git(path, "update-index", flag, "--", "example.txt")
        index = Path(git(path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
        before = index.read_bytes()
        refs = git(self.repo, "show-ref")
        # Flags alone make cleanliness uncertain, even before a hidden edit.
        self.assertEqual(prune.prune(self.config, unit["id"])["work"][0]["state"], "kept")
        write(path / "example.txt", "valuable hidden edit\n")
        for apply in (False, True):
            with self.subTest(apply=apply):
                row, = prune.prune(self.config, unit["id"], apply=apply, delete_branches=True)["work"]
                self.assertEqual(row["state"], "kept")
                self.assertIn("index", row["reasons"][0])
                self.assertEqual((path / "example.txt").read_text(), "valuable hidden edit\n")
                self.assertEqual(index.read_bytes(), before)
                self.assertEqual(git(self.repo, "show-ref"), refs)

    def test_prune_refuses_assume_unchanged_entries(self):
        self.check_hidden_index_changes(["--assume-unchanged"])

    def test_prune_refuses_skip_worktree_entries(self):
        self.check_hidden_index_changes(["--skip-worktree"])

    def test_prune_refuses_combined_hidden_index_flags(self):
        self.check_hidden_index_changes(["--assume-unchanged", "--skip-worktree"])

    def test_cleanup_refuses_hidden_index_changes_without_modifying_index(self):
        unit, path, _ = self.cleanup_fixture()
        git(path, "update-index", "--assume-unchanged", "--", "example.txt")
        write(path / "example.txt", "valuable hidden edit\n")
        index = Path(git(path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
        before = index.read_bytes()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaisesRegex(HubError, "index"):
                work.cleanup(self.config, unit["id"], apply)
        self.assertEqual((path / "example.txt").read_text(), "valuable hidden edit\n")
        self.assertEqual(index.read_bytes(), before)

    def test_prune_rechecks_index_flags_immediately_before_removal(self):
        unit, path, _ = self.cleanup_fixture()
        original = prune.apply_unit
        def hide_edit(*args):
            git(path, "update-index", "--assume-unchanged", "--", "example.txt")
            write(path / "example.txt", "hidden after assessment\n")
            return original(*args)
        with patch.object(prune, "apply_unit", side_effect=hide_edit):
            result = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["work"][0]["state"], "failed")
        self.assertEqual(result["work"][0]["removed_worktrees"], [])
        self.assertEqual((path / "example.txt").read_text(), "hidden after assessment\n")

    def test_prune_refuses_stale_or_missing_refs_and_unreachable_live_remote(self):
        unit, path, pr = self.cleanup_fixture()
        write(self.repo / "later.txt", "later default work")
        commit(self.repo)
        git(self.repo, "push", "origin", "main")
        git(self.repo, "update-ref", "refs/remotes/origin/main", pr["merge_commit_sha"])
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertIn("stale", row["reasons"][0])
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(prune.prune(self.config, unit["id"], apply=True)["work"][0]["state"], "kept")
        (self.root / "origin.git").rename(self.root / "offline-origin.git")
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertIn("live origin", row["reasons"][0])
        self.assertTrue(path.exists())

    def test_prune_does_not_infer_completion_or_touch_foreign_worktrees(self):
        unit, path, _ = self.cleanup_fixture()
        for state in ("planned", "prepared"):
            unit["status"] = state
            work.persist(self.config, unit)
            self.assertEqual(prune.prune(self.config, unit["id"], apply=True)["work"][0]["state"], "kept")
        unit["status"] = "review"
        work.persist(self.config, unit)
        moved = self.root / "foreign-worktree"
        git(self.repo, "worktree", "move", str(path), str(moved))
        row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)["work"]
        self.assertIn("outside its recorded worktree", row["reasons"][0])
        self.assertTrue(moved.exists())

    def test_prune_requires_commits_in_both_local_and_live_default(self):
        unit, path, pr = self.cleanup_fixture()
        git(self.repo, "update-ref", "refs/heads/main", unit["repos"]["alpha"]["base"])
        self.assertEqual(prune.prune(self.config, unit["id"], apply=True)["work"][0]["state"], "kept")
        git(self.repo, "update-ref", "refs/heads/main", pr["merge_commit_sha"])
        git(self.root / "origin.git", "update-ref", "refs/heads/main", unit["repos"]["alpha"]["base"])
        git(self.repo, "update-ref", "refs/remotes/origin/main", unit["repos"]["alpha"]["base"])
        row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertIn("local and live default", row["reasons"][0])
        self.assertTrue(path.exists())

    def test_prune_uses_original_history_instead_of_local_replacements(self):
        unit, path, pr = self.cleanup_fixture()
        write(path / "extra.txt", "unmerged local work")
        commit(path)
        identity = ["-c", "user.name=Hub Test", "-c", "user.email=hub@example.invalid"]
        # Simulate local history editing that makes default appear to contain
        # an otherwise unmerged commit, without altering the remote's objects.
        extra = git(self.repo, *identity, "commit-tree", git(path, "rev-parse", "HEAD^{tree}"),
                    "-p", unit["repos"]["alpha"]["base"], "-m", "unmerged alternate history")
        git(self.repo, "update-ref", "refs/heads/" + unit["repos"]["alpha"]["branch"], extra)
        replacement = git(self.repo, *identity, "commit-tree", git(self.repo, "rev-parse", "main^{tree}"),
                          "-p", extra, "-m", "local replacement history")
        git(self.repo, "replace", pr["merge_commit_sha"], replacement)
        row, = prune.prune(self.config, unit["id"], delete_branches=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertTrue(path.exists())

    def test_prune_refuses_locked_and_wrong_branch_worktrees(self):
        unit, path, _ = self.cleanup_fixture()
        git(self.repo, "worktree", "lock", str(path))
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertIn("locked", row["reasons"][0])
        git(self.repo, "worktree", "unlock", str(path))
        git(path, "checkout", "-b", "unexpected")
        row, = prune.prune(self.config, unit["id"], apply=True)["work"]
        self.assertIn("branch changed", row["reasons"][0])
        self.assertTrue(path.exists())

    def test_prune_checks_all_execution_repositories_before_removing_any(self):
        unit, path, _ = self.cleanup_fixture()
        beta = repository(self.root / "beta")
        self.register((self.instance / "repos.toml").read_text() + '\n[[repos]]\nname="beta"\nremote="https://github.com/example/beta.git"\n')
        unit["repos"]["beta"] = {"branch": work.branch_name(unit, "beta"), "base": git(beta, "rev-parse", "HEAD")}
        unit["status"] = "planned"
        work.persist(self.config, unit)
        work.prepare(self.config, unit["id"])
        write(work.location(self.config, unit["id"], "beta") / "new.txt", "unreviewed work")
        work.report(self.config, unit["id"], "Review both fixtures")
        row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertTrue(path.exists())
        self.assertTrue(work.location(self.config, unit["id"], "beta").exists())

    def test_prune_aggregate_preserves_unready_work(self):
        unit, path, _ = self.cleanup_fixture()
        unready = self.unit()
        result = prune.prune(self.config, apply=True)
        states = {row["id"]: row["state"] for row in result["work"]}
        self.assertEqual(states, {unit["id"]: "cleaned", unready["id"]: "kept"})
        self.assertFalse(path.exists())
        self.assertTrue(work.location(self.config, unready["id"], "alpha").exists())

    def test_prune_reports_invalid_records_without_losing_other_results(self):
        unit, path, _ = self.cleanup_fixture()
        broken = work.create(self.config, "Broken fixture", "Test corrupt metadata", [], "Report it honestly")
        del broken["sessions"]
        work.persist(self.config, broken)
        result = prune.prune(self.config, apply=True)
        states = {row["id"]: row["state"] for row in result["work"]}
        self.assertEqual(states, {unit["id"]: "cleaned", broken["id"]: "kept"})
        self.assertFalse(path.exists())
        row = next(r for r in result["work"] if r["id"] == broken["id"])
        self.assertEqual(row["reasons"], ["Invalid execution metadata; inspect it manually"])

    def test_prune_rechecks_evidence_before_removal(self):
        unit, path, _ = self.cleanup_fixture()
        original = prune.unit_plan
        calls = 0
        def change_before_recheck(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                write(path / "new-work.txt", "work arriving after assessment")
            return original(*args, **kwargs)
        with patch.object(prune, "unit_plan", side_effect=change_before_recheck):
            row, = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)["work"]
        self.assertEqual(row["state"], "kept")
        self.assertIn("changed during assessment", row["reasons"][0])
        self.assertTrue((path / "new-work.txt").exists())

    def test_prune_reports_removal_failure_and_retains_branch(self):
        unit, path, _ = self.cleanup_fixture()
        original = prune.run
        def refuse_removal(args, **kwargs):
            if "worktree" in args and "remove" in args:
                raise HubError("Fixture Git removal refusal")
            return original(args, **kwargs)
        with patch.object(prune, "run", side_effect=refuse_removal):
            result = prune.prune(self.config, unit["id"], apply=True, delete_branches=True)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["work"][0]["state"], "failed")
        self.assertEqual(result["work"][0]["deleted_branches"], [])
        self.assertEqual(work.load(self.config, unit["id"])["status"], "review")
        self.assertTrue(path.exists())

    def test_prune_reports_actual_removal_if_metadata_write_fails(self):
        unit, path, _ = self.cleanup_fixture()
        with patch.object(work, "persist", side_effect=OSError("fixture disk failure")):
            result = prune.prune(self.config, unit["id"], apply=True)
        self.assertEqual(result["exit_code"], 1)
        row, = result["work"]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["removed_worktrees"], ["alpha"])
        self.assertFalse(path.exists())
        self.assertEqual(work.load(self.config, unit["id"])["status"], "review")
        self.assertEqual(prune.prune(self.config, unit["id"], apply=True, delete_branches=True)["work"][0]["state"], "cleaned")

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

    def test_claude_orchestrator_plan_keeps_native_permissions(self):
        self.config.runtime = "claude"
        with patch("agent_hub.claude_adapter.binary", return_value="claude"):
            result = agents.plan(self.config, "orchestrator")
        self.assertEqual(result["role"], "orchestrator")
        self.assertEqual(Path(result["cwd"]).resolve(), self.instance.resolve())
        self.assertIn("plan", result["command"])
        self.assertIn("--tools", result["command"])
        self.assertNotIn("bypassPermissions", result["command"])
        self.assertNotIn("dangerously-skip-permissions", result["command"])

    def test_claude_worker_plan_is_restricted_and_no_unsandboxed_retry(self):
        unit = self.unit()
        self.config.runtime = "claude"
        with patch("agent_hub.claude_adapter.binary", return_value="claude"):
            result = agents.plan(self.config, "worker", unit["id"])
        command = result["command"]
        self.assertIn("--restricted", command)
        self.assertIn("dontAsk", command)
        self.assertNotIn("--add-dir", command)
        self.assertIn("--disallowedTools", command)
        settings = json.loads(command[command.index("--settings") + 1])
        self.assertTrue(settings["sandbox"]["enabled"])
        self.assertTrue(settings["sandbox"]["failIfUnavailable"])
        self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"])
        self.assertTrue(settings["permissions"]["blockWritesOutsideWorkingDirectories"])
        self.assertIn(str(work.location(self.config, unit["id"], "alpha") / ".git"),
                      settings["sandbox"]["filesystem"]["denyWrite"])
        root = work.location(self.config, unit["id"])
        path = root / "alpha"
        common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
        self.assertIn(str(common), settings["permissions"]["additionalDirectories"])
        self.assertIn(str(common), settings["sandbox"]["filesystem"]["denyWrite"])
        self.assertTrue(settings["permissions"]["blockReadsOutsideWorkingDirectories"])
        for target in (root / "AGENTS.md", root / "CLAUDE.md",
                       path / "AGENTS.md", path / "CLAUDE.md", path / ".git",
                       path / ".mcp.json", path / ".claude", common):
            rule = "Edit(//" + target.resolve().as_posix().lstrip("/") + ")"
            self.assertIn(rule, settings["permissions"]["deny"])
            self.assertIn(rule[:-1] + "/**)", settings["permissions"]["deny"])
        self.assertNotIn("Write", settings["permissions"]["deny"])

    def test_claude_worker_launch_fails_closed_without_probe(self):
        unit = self.unit()
        self.config.runtime = "claude"
        with patch("agent_hub.claude_adapter.binary", return_value="claude"), patch(
                "agent_hub.claude_adapter.sandbox_probe", return_value={"passed": False}), patch(
                "agent_hub.agents.execute") as execute:
            with self.assertRaises(HubError):
                agents.launch(self.config, "worker", unit["id"])
            execute.assert_not_called()
        self.assertFalse(work.load(self.config, unit["id"])["sessions"])

    def test_claude_probe_without_native_execution_cannot_pass(self):
        unit = self.unit()
        self.config.runtime = "claude"
        with patch("agent_hub.claude_adapter.binary", return_value="claude"), patch(
                "agent_hub.claude_adapter.execute",
                return_value=subprocess.CompletedProcess([], 0, stdout='{"result":"not a tool execution"}')):
            report = agents.sandbox_probe(self.config, unit["id"])
        self.assertFalse(report["passed"])
        self.assertEqual(repos.sandbox_probe_status(self.config, "claude"), "blocked")
        root = work.location(self.config, unit["id"])
        self.assertEqual(list(root.glob(".hub-probe-*")), [])

    def test_claude_session_records_provider_and_omits_payloads(self):
        unit = self.unit()
        self.config.runtime = "claude"
        secret = "ghp_" + "z" * 40
        with patch("agent_hub.claude_adapter.binary", return_value="claude"), patch(
                "agent_hub.agents.sandbox_probe", return_value={"passed": True}), patch(
                "agent_hub.agents.execute",
                return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({"result": secret}), stderr=secret)):
            result = agents.launch(self.config, "worker", unit["id"], noninteractive=True)
        self.assertEqual(work.load(self.config, unit["id"])["sessions"][0]["runtime"], "claude")
        self.assertNotIn(secret, Path(result["log"]).read_text())
        self.assertIn("exit_code", Path(result["log"]).read_text())

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
