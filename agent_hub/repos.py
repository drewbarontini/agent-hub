from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .common import CORE, HubError, git, remote_id, run, write


def inspect(repo):
    path = repo["path"]
    row = {"name": repo["name"], "registered": True, "available": False,
           "visible": repo["visible"], "path": str(path), "problem": None}
    if not path.exists():
        row["problem"] = "missing"
        return row
    try:
        top = git(path, "rev-parse", "--show-toplevel")
        if Path(top).resolve() != path.resolve():
            raise HubError("path is not the repository root")
        origin = git(path, "config", "--get", "remote.origin.url")
        if remote_id(origin) != remote_id(repo["remote"]):
            raise HubError("origin does not match registry")
        git(path, "rev-parse", "--verify", "refs/heads/" + repo["default_branch"])
        row.update(available=True,
                   branch=git(path, "symbolic-ref", "--short", "HEAD", check=False) or "(detached)",
                   dirty=bool(git(path, "status", "--porcelain=v1", "--untracked-files=all")))
    except HubError as exc:
        row["problem"] = str(exc)
    return row


def available(repo):
    row = inspect(repo)
    if not row["available"]:
        raise HubError(f"Repository {repo['name']} unavailable: {row['problem']}")
    return row


def bootstrap(config):
    result = []
    for repo in config.repos.values():
        if not repo["path"].exists() and repo["checkout"]:
            repo["path"].parent.mkdir(parents=True, exist_ok=True)
            run(["git", "clone", "--branch", repo["default_branch"], "--", repo["remote"], repo["path"]])
        result.append(inspect(repo))
    return result


def discover(roots, depth=2):
    """Explicit roots only. Do not follow symlinks or enter repositories."""
    if not roots:
        raise HubError("Discovery requires at least one explicitly authorized --root")
    if depth < 0 or depth > 5:
        raise HubError("Discovery depth must be 0–5")
    rows = []
    seen = set()
    def visit(path, level):
        if path.is_symlink() or path in seen:
            return
        seen.add(path)
        if (path / ".git").exists():
            try:
                origin = git(path, "config", "--get", "remote.origin.url", check=False)
                # Do not expose an unsafe URL found in existing Git config.
                safe = bool(origin)
                if origin:
                    try:
                        remote_id(origin)
                    except HubError:
                        safe = False
                rows.append({"name": path.name, "path": str(path), "has_origin": bool(origin),
                             "origin_safe": safe,
                             "branch": git(path, "symbolic-ref", "--short", "HEAD", check=False),
                             "instructions": [f for f in ("AGENTS.md", "CLAUDE.md") if (path / f).is_file()],
                             "native_skills": [f for f in (".agents/skills", ".claude/skills") if (path / f).is_dir()],
                             "mcp_configuration_present": (path / ".mcp.json").is_file()})
            except HubError:
                rows.append({"path": str(path), "problem": "Git metadata inaccessible"})
            return
        if level >= depth:
            return
        try:
            for entry in sorted(path.iterdir()):
                if entry.is_dir() and not entry.name.startswith(".") and entry.name not in {"node_modules", "vendor", "venv"}:
                    visit(entry, level + 1)
        except OSError:
            rows.append({"path": str(path), "problem": "directory inaccessible"})
    for raw in roots:
        p = Path(raw).expanduser().absolute()
        if not p.is_dir():
            rows.append({"path": str(p), "problem": "missing discovery root"})
        else:
            visit(p, 0)
    return rows


def workspace(config):
    target = config.root / ".hub" / "hub.code-workspace"
    folders = [{"name": "Hub Instance", "path": os.path.relpath(config.root, target.parent)}]
    for repo in config.repos.values():
        if repo["visible"] and inspect(repo)["available"]:
            folders.append({"name": repo["name"], "path": os.path.relpath(repo["path"], target.parent)})
    pinned = config.root / ".hub/cores" / config.lock["commit"] / "bin/hub"
    command = [sys.executable, str(pinned), "--instance", str(config.root)]
    tasks = []
    for name, args in [("Hub: status", ["status"]), ("Hub: doctor", ["doctor"]),
                       ("Hub: Orchestrator", ["agent", "orchestrator", "--launch"])]:
        tasks.append({"label": name, "type": "process", "command": command[0], "args": command[1:] + args,
                      "options": {"cwd": str(config.root)}, "problemMatcher": [],
                      "presentation": {"panel": "dedicated"}})
    data = {"folders": folders, "settings": {"terminal.integrated.defaultLocation": "editor"},
            "extensions": {"recommendations": ["openai.chatgpt"]},
            "tasks": {"version": "2.0.0", "tasks": tasks}}
    write(target, json.dumps(data, indent=2) + "\n")
    return {"workspace": str(target), "folders": [f["name"] for f in folders],
            "layout": "Arrange sidebar and editor terminals manually; no agent session is auto-started"}


def guard(repo_path, default_branch):
    branch = git(repo_path, "symbolic-ref", "--short", "HEAD", check=False)
    if branch == default_branch or not branch:
        raise HubError("Protected default branch or detached HEAD: use an isolated task worktree")


def install_guard(config, name):
    """Explicit opt-in: never replace an existing hook or hooksPath."""
    import shlex
    repo = config.repo(name)
    available(repo)
    if git(repo["path"], "config", "--get", "core.hooksPath", check=False):
        raise HubError("Existing core.hooksPath: integrate the guard manually")
    common = Path(git(repo["path"], "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo["path"] / common
    hooks = common.resolve() / "hooks"
    destinations = [hooks / "pre-commit", hooks / "pre-push"]
    if any(p.exists() or p.is_symlink() for p in destinations):
        raise HubError("Existing hooks: integrate the guard manually")
    args = [sys.executable, str(CORE / "bin/hub"), "guard-check", "--branch", repo["default_branch"]]
    if not repo["protected"]:
        raise HubError("Repository is not configured as protected")
    for p in destinations:
        hook_args = args + (["--push"] if p.name == "pre-push" else [])
        write(p, "#!/bin/sh\nexec " + shlex.join(hook_args) + "\n")
        p.chmod(0o755)
    return {"installed": [str(p) for p in destinations],
            "limits": "Hooks guard commits and pushes only; --no-verify and filesystem edits bypass hooks"}


def executable(config, name):
    value = config.data.get("tools", {}).get(name) or shutil.which(name)
    if not value and name == "codex":
        bundled = Path("/Applications/Codex.app/Contents/Resources/codex")
        if bundled.is_file():
            value = str(bundled)
    return value if value and shutil.which(value) else None


def resources(config):
    rows = []
    for item in config.resources:
        row = {"name": item["name"], "kind": item["kind"], "configured": True,
               "connectivity": "not verified", "available": False}
        if "path" in item:
            p = config.path(item["path"])
            row["available"] = p.exists()
            row["availability"] = "local path present" if p.exists() else "local path missing"
        elif "executable" in item:
            row["available"] = bool(executable(config, item["executable"]))
            row["availability"] = "executable present" if row["available"] else "executable missing"
        else:
            row["availability"] = "requires provider authentication or explicit connectivity check"
        if item["kind"] in {"mcp", "work"}:
            row["connectivity"] = "unsupported by Core; verify in the native provider"
        rows.append(row)
    return rows


def sandbox_probe_status(config, runtime="codex"):
    """Summarize saved local sandbox evidence without executing a provider."""
    if runtime not in {"codex", "claude"}:
        raise HubError("Unknown runtime for sandbox probe")
    filename = "last-claude-sandbox-probe.json" if runtime == "claude" else "last-sandbox-probe.json"
    path = config.root / ".hub" / filename
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "not-probed"
    except (OSError, UnicodeError, ValueError, RecursionError):
        return "unknown"
    if not isinstance(report, dict):
        return "unknown"
    passed, exit_code, checks = (report.get(key) for key in ("passed", "exit_code", "checks"))
    if type(passed) is not bool or type(exit_code) is not int or not isinstance(checks, dict):
        return "unknown"
    if not passed:
        return "blocked" if exit_code != 0 else "unknown"
    blocked = checks.get("outside_and_metadata_blocked")
    if (exit_code != 0 or checks.get("inside_write") is not True
            or not isinstance(blocked, list) or not blocked or any(item is not True for item in blocked)):
        return "unknown"
    if runtime == "claude":
        readable = checks.get("git_metadata_readable")
        if not isinstance(readable, list) or not readable or any(item is not True for item in readable):
            return "unknown"
    return "passed"


def doctor(config):
    checks = [{"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]},
              {"name": "git", "ok": bool(shutil.which("git"))},
              {"name": config.runtime, "ok": bool(executable(config, config.runtime))},
              {"name": "code", "ok": bool(executable(config, "code")), "required": False}]
    for repo in config.repos.values():
        row = inspect(repo)
        checks.append({"name": "repo:" + repo["name"], "ok": row["available"], "detail": row["problem"]})
    for row in resources(config):
        checks.append({"name": "resource:" + row["name"], "ok": row["available"],
                       "required": False, "detail": row["availability"], "connectivity": row["connectivity"]})
    checkout = config.root / ".hub/cores" / config.lock["commit"]
    try:
        ok = checkout.is_dir() and git(checkout, "rev-parse", "HEAD") == config.lock["commit"]
        ok = ok and not bool(git(checkout, "status", "--porcelain", "--untracked-files=all"))
    except HubError:
        ok = False
    checks.append({"name": "pinned-core", "ok": ok})
    return {"ready": all(x["ok"] for x in checks if x.get("required", True)), "checks": checks,
            "agent_execution": {
                "runtime": config.runtime,
                "launch_adapter_implemented": config.runtime in {"codex", "claude"},
                "last_sandbox_probe": {"runtime": config.runtime, "status": sandbox_probe_status(config, config.runtime)},
                "worker_execution": "unverified"},
            "authentication": "Not inferred from executable presence; verify in the selected runtime"}
