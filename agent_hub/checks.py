"""Explicit checks and recorded-base diagnostics, with local execution receipts."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import uuid
from pathlib import Path

from .common import HubError, git, run, sanitize, save
from . import setup

FILE_LIMIT = 200


def configuration(value):
    if not isinstance(value, dict) or set(value) - {"commands", "timeout"}:
        raise HubError("Invalid repository checks configuration")
    if not value:
        return {}
    spec = setup.configuration(value)
    return {key: spec[key] for key in ("commands", "timeout")}


def fingerprint(repo):
    value = {"checks": repo.get("checks", {}), "environment_dirs": repo.get("setup", {}).get("environment_dirs", [])}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def observation(repo, unit, name):
    receipts = unit.get("checks", {})
    if not isinstance(receipts, dict):
        return {"state": "invalid-receipt", "passed": None}
    latest = receipts.get(name)
    if not latest:
        return {"state": "not-run" if repo.get("checks", {}).get("commands") else "unconfigured", "passed": None}
    if not isinstance(latest, dict) or "state" not in latest:
        return {"state": "invalid-receipt", "passed": None}
    if latest.get("configuration") != fingerprint(repo):
        return {"state": "configuration-changed", "passed": None}
    return {key: latest.get(key) for key in ("state", "passed", "receipt")}


def snapshot(path):
    from .work import changed_files
    files = changed_files(path, ignored=True)
    observed = []
    for item in files[:FILE_LIMIT]:
        value = dict(item)
        try:
            metadata = (path / item["path"]).lstat()
            value["metadata"] = [metadata.st_mode, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns]
        except FileNotFoundError:
            value["metadata"] = None
        except OSError:
            raise HubError("Cannot observe changed-path metadata")
        observed.append(value)
    return {"files": observed, "total": len(files), "truncated": len(files) > FILE_LIMIT,
            "scope": "Git status paths and file metadata; ignored directories may summarize contents"}


def changed(before, after):
    first = {item["path"]: item for item in before["files"]}
    last = {item["path"]: item for item in after["files"]}
    return sorted(path for path in first.keys() | last.keys() if first.get(path) != last.get(path))


def run_checks(entry, path, spec, environment, persist, validate):
    entry.update(state="running", passed=None, commands=[])
    validate()
    previous = entry["files_before"] = snapshot(path)
    persist()
    for command in spec["commands"]:
        step = {"argv": sanitize(command), "exit_code": None, "state": "running"}
        entry["commands"].append(step)
        persist()
        try:
            result = run(command, cwd=path, env=environment, text=False, timeout=spec["timeout"], check=False)
            step.update(exit_code=result.returncode, state="passed" if result.returncode == 0 else "failed")
        except HubError as exc:
            step.update(state="failed", problem=str(exc))
        except KeyboardInterrupt:
            step["state"] = "interrupted"
            entry.update(state="interrupted", passed=False)
            persist()
            raise
        validate()
        current = snapshot(path)
        step.update(files_after=current, observed_changes=changed(previous, current))
        previous = current
        persist()
    passed = all(step["state"] == "passed" for step in entry["commands"])
    entry.update(state="passed" if passed else "failed", passed=passed, files_after=previous,
                 observed_changes=changed(entry["files_before"], previous))
    persist()


def baseline_identity(repo, path, base):
    if path.is_symlink() or not path.is_dir():
        raise HubError("Baseline path is missing or unsafe")
    if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path.resolve():
        raise HubError("Baseline root changed")
    expected = git(repo["path"], "rev-parse", "--path-format=absolute", "--git-common-dir")
    if git(path, "rev-parse", "--path-format=absolute", "--git-common-dir") != expected:
        raise HubError("Baseline repository identity changed")
    if git(path, "rev-parse", "HEAD") != base or git(path, "symbolic-ref", "-q", "HEAD", check=False):
        raise HubError("Baseline is no longer detached at its recorded base")


def baseline(config, unit, name, root, spec, entry, persist):
    from . import prune, work
    repo, base = config.repo(name), unit["repos"][name]["base"]
    path = setup.local_path(root, f"{name}/base")
    result = {"base": base, "directory": str(path), "state": "pending", "passed": None, "retained": False}
    entry["baseline"] = result
    persist()
    try:
        prune.require_local_history(repo)
        if path.exists() or path.is_symlink():
            raise HubError("Baseline destination already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Retain the location even if Git partially creates a checkout and fails.
        result["retained"] = True
        run(["git", "-C", repo["path"], "worktree", "add", "--detach", path, base])
        environment = dict(os.environ)
        for variable in repo.get("setup", {}).get("environment_dirs", []):
            directory = setup.local_path(root, f"{name}/environment/{variable}")
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                raise HubError("Baseline environment directory is unsafe")
            directory.mkdir(parents=True, exist_ok=True)
            environment[variable] = str(directory)
        validate = lambda: baseline_identity(repo, path, base)
        run_checks(result, path, spec, environment, persist, validate)
    except HubError as exc:
        result.update(state="unavailable", passed=None, problem=str(exc), retained=path.exists() or path.is_symlink())
        persist()
    except KeyboardInterrupt:
        result.update(state="interrupted", passed=False, retained=True)
        persist()
        raise
    if result["retained"]:
        try:
            baseline_identity(repo, path, base)
            work.check_index_flags(path)
            if run(["git", "--no-optional-locks", "-C", path, "status", "--porcelain", "-z",
                    "--untracked-files=all", "--ignored=matching"], text=False).stdout:
                raise HubError("Baseline artifacts retained for inspection")
            run(["git", "-C", repo["path"], "worktree", "remove", path])
            result.update(retained=False, cleanup="Removed clean disposable baseline without force")
        except HubError as exc:
            result["cleanup"] = str(exc)
    result["comparison"] = "base-passed" if result["passed"] is True else "both-failed" if result["passed"] is False else "unavailable"
    result["interpretation"] = "Diagnostic only; setup and environments may differ, and matching results do not prove causality"
    persist()


def execute(config, identifier, names=None, *, plan=False, skip=False, compare_base=False):
    from . import work
    from .repos import available
    if plan and skip:
        raise HubError("Choose check planning or skipping")
    with contextlib.nullcontext() if plan else work.mutation(config):
        unit = work.load(config, identifier)
        if unit["status"] not in {"prepared", "review"}:
            raise HubError("Prepare work before checking it")
        if any(s["status"] in {"running", "interrupted"} for s in unit["sessions"]):
            raise HubError("Inspect and release running or interrupted sessions before checks")
        selected = list(dict.fromkeys(names if names is not None else unit["repos"]))
        if not selected or set(selected) - set(unit["repos"]):
            raise HubError("Checks require selected execution repositories")
        plans = []
        for name in selected:
            repo = config.repo(name)
            available(repo)
            work.validate_tree(config, unit, name)
            if not skip:
                setup.environment_paths(config, identifier, name, repo.get("setup", {}).get("environment_dirs", []))
            plans.append({"name": name, "commands": sanitize(repo.get("checks", {}).get("commands", [])),
                          "base": unit["repos"][name]["base"]})
        if plan:
            return {"id": identifier, "planned": True, "passed": None, "baseline_requested": compare_base, "repos": plans}
        run_id = "C-" + uuid.uuid4().hex[:12]
        root = setup.local_path(work.location(config, identifier), f".checks/{run_id}")
        if root.exists() or root.is_symlink():
            raise HubError("Check receipt destination already exists")
        root.mkdir(parents=True)
        receipt = {"id": identifier, "run": run_id, "recorded_at": work.now(), "receipt": str(root / "receipt.json"),
                   "baseline_requested": compare_base, "selected_repositories": selected, "passed": None, "repos": []}

        def persist():
            save(root / "receipt.json", sanitize(receipt))
            latest = unit.setdefault("checks", {})
            for entry in receipt["repos"]:
                latest[entry["name"]] = {key: entry.get(key) for key in ("state", "passed", "configuration", "head")}
                latest[entry["name"]].update(run=run_id, recorded_at=receipt["recorded_at"], receipt=receipt["receipt"])
            work.persist(config, unit)

        persist()
        for name in selected:
            repo = config.repo(name)
            path = work.validate_tree(config, unit, name)
            spec = repo.get("checks", {})
            entry = {"name": name, "state": "skipped" if skip else "unconfigured", "passed": None if skip else False,
                     "configuration": fingerprint(repo), "head": git(path, "rev-parse", "HEAD"), "commands": []}
            receipt["repos"].append(entry)
            persist()
            if skip or not spec.get("commands"):
                continue
            try:
                environment = dict(os.environ)
                for variable, directory in setup.environment_paths(
                        config, identifier, name, repo.get("setup", {}).get("environment_dirs", [])).items():
                    directory.mkdir(parents=True, exist_ok=True)
                    environment[variable] = str(directory)
                run_checks(entry, path, spec, environment, persist, lambda: work.validate_tree(config, unit, name))
                if compare_base and entry["passed"] is False:
                    baseline(config, unit, name, root, spec, entry, persist)
            except HubError as exc:
                entry.update(state="failed", passed=False, problem=str(exc))
            except KeyboardInterrupt:
                entry.update(state="interrupted", passed=False)
                receipt["passed"] = False
                persist()
                raise
            persist()
        if skip:
            receipt["passed"] = None
        else:
            receipt["passed"] = all(entry["passed"] is True for entry in receipt["repos"])
        receipt["interpretation"] = "Recorded process results and bounded file observations; canonical completion is separate"
        persist()
        return receipt
