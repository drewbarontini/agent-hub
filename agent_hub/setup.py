"""Explicit repository setup; receipts never authorize artifact deletion."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .common import HubError, run, sanitize


def relative(value):
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise HubError("Setup paths must be nonempty relative paths")
    path = Path(value)
    protected = {"..", ".git", ".hub", ".codex", ".agents", ".aws", "agents.md", "claude.md"}
    if path.is_absolute() or not path.parts or any(p.casefold() in protected for p in path.parts):
        raise HubError("Setup paths cannot escape their repository or target protected metadata")
    return path.as_posix()


def configuration(value):
    if not isinstance(value, dict) or set(value) - {"commands", "links", "environment_dirs", "timeout"}:
        raise HubError("Invalid repository setup configuration")
    if not value:
        return {}
    commands = value.get("commands", [])
    if not isinstance(commands, list) or any(
            not isinstance(c, list) or not c or any(not isinstance(a, str) or "\0" in a for a in c) or not c[0]
            for c in commands):
        raise HubError("Setup commands must be nonempty argument arrays")
    links = value.get("links", [])
    if not isinstance(links, list):
        raise HubError("Setup links must be a list")
    normalized, targets = [], []
    for link in links:
        if not isinstance(link, dict) or set(link) != {"source", "target"}:
            raise HubError("Setup links require source and target relative paths")
        item = {key: relative(link[key]) for key in ("source", "target")}
        target = Path(item["target"])
        if any(target == p or target in p.parents or p in target.parents for p in targets):
            raise HubError("Setup link targets cannot overlap")
        targets.append(target)
        normalized.append(item)
    variables = value.get("environment_dirs", [])
    if not isinstance(variables, list) or any(
            not isinstance(v, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", v)
            or v.upper() in {"PATH", "HOME", "CODEX_HOME", "HUB_INSTANCE", "HUB_OVERLAY"} for v in variables):
        raise HubError("Setup environment_dirs requires tool directory variable names")
    if len({v.casefold() for v in variables}) != len(variables):
        raise HubError("Setup environment directory names must be distinct")
    timeout = value.get("timeout", 300)
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise HubError("Setup timeout must be 1–3600 seconds")
    return {"commands": commands, "links": normalized, "environment_dirs": variables, "timeout": timeout}


def fingerprint(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def local_path(root, value):
    path = root / relative(value)
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise HubError("Setup path has a symlink or non-directory parent")
    return path


def link_plan(repo, tree, links, managed):
    plans = []
    tracked = []
    if links:
        tracked = [os.fsdecode(p).casefold() for p in run(
            ["git", "-C", tree, "ls-files", "-z"], text=False).stdout.split(b"\0") if p]
    for link in links:
        source = local_path(repo["path"], link["source"])
        target = local_path(tree, link["target"])
        if source.is_symlink() or not (source.is_file() or source.is_dir()):
            raise HubError("Setup source is missing, unsupported or a symlink")
        key = link["target"].casefold()
        if any(p == key or p.startswith(key + "/") or key.startswith(p + "/") for p in tracked):
            raise HubError("Setup link would replace tracked content")
        expected = os.path.relpath(source, target.parent)
        reused = target.is_symlink() and os.readlink(target) == expected and link in managed
        if (target.exists() or target.is_symlink()) and not reused:
            raise HubError("Setup link conflicts with existing unmanaged content")
        plans.append(dict(link, reused=reused))
    return plans


def environment_paths(config, identifier, name, variables):
    from .work import location
    paths = {}
    for variable in variables:
        path = local_path(location(config, identifier), f"setup/{name}/environment/{variable}")
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise HubError("Setup environment directory is unsafe")
        paths[variable] = path
    return paths


def observation(config, unit, name):
    receipts = unit.get("setup", {})
    if not isinstance(receipts, dict):
        return {"state": "invalid-receipt", "ready": None}
    receipt = receipts.get(name)
    if not receipt:
        return {"state": "not-run" if config.repo(name).get("setup") else "unconfigured", "ready": None}
    if not isinstance(receipt, dict) or "state" not in receipt:
        return {"state": "invalid-receipt", "ready": None}
    if receipt.get("configuration") != fingerprint(config.repo(name).get("setup", {})):
        return {"state": "configuration-changed", "ready": None}
    return {"state": receipt["state"], "ready": receipt.get("ready")}


def cleanup_notice(unit, name):
    if unit.get("setup", {}).get(name):
        return "; setup artifacts are retained too—inspect the setup receipt and remove artifacts explicitly"
    return ""


def execute(config, identifier, names=None, *, apply=False, skip=False):
    from . import work
    from .repos import available
    if apply and skip:
        raise HubError("Choose setup apply or skip")
    with work.mutation(config):
        unit = work.load(config, identifier)
        if unit["status"] not in {"prepared", "review"}:
            raise HubError("Prepare work before setup")
        if any(s["status"] in {"running", "interrupted"} for s in unit["sessions"]):
            raise HubError("Inspect and release running or interrupted sessions before setup")
        selected = list(dict.fromkeys(names if names is not None else unit["repos"]))
        if not selected or set(selected) - set(unit["repos"]):
            raise HubError("Setup requires selected execution repositories")
        plans = []
        for name in selected:
            repo = config.repo(name)
            available(repo)
            tree = work.validate_tree(config, unit, name)
            spec = repo.get("setup", {})
            previous = unit.get("setup", {}).get(name, {})
            links = [] if skip else link_plan(repo, tree, spec.get("links", []), previous.get("links", []))
            if not skip:
                environment_paths(config, identifier, name, spec.get("environment_dirs", []))
            plans.append({"name": name, "configured": bool(spec), "commands": sanitize(spec.get("commands", [])),
                          "links": links, "environment_dirs": spec.get("environment_dirs", [])})
        if not apply and not skip:
            return {"id": identifier, "applied": False, "ready": None, "repos": plans,
                    "next": "Use --apply to run setup, or --skip to record a deliberate skip"}
        results = []
        for plan in plans:
            name = plan["name"]
            repo, tree = config.repo(name), work.validate_tree(config, unit, name)
            available(repo)
            spec = repo.get("setup", {})
            previous = unit.setdefault("setup", {}).get(name, {})
            receipt = {"state": "skipped" if skip else "running" if spec else "unconfigured", "ready": None,
                       "configuration": fingerprint(spec), "recorded_at": work.now(), "commands": [],
                       "links": list(previous.get("links", [])), "environment_dirs": spec.get("environment_dirs", [])}
            unit["setup"][name] = receipt
            work.persist(config, unit)
            if skip or not spec:
                results.append(dict(receipt, name=name))
                continue
            try:
                # Recheck at execution time; an earlier preview grants no permission
                # to replace entries that appeared or changed afterward.
                links = link_plan(repo, tree, spec["links"], receipt["links"])
                directories = environment_paths(config, identifier, name, spec["environment_dirs"])
                for link in links:
                    if link["reused"]:
                        continue
                    target = local_path(tree, link["target"])
                    source = local_path(repo["path"], link["source"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(os.path.relpath(source, target.parent))
                    receipt["links"].append({key: link[key] for key in ("source", "target")})
                    work.persist(config, unit)
                environment = dict(os.environ)
                for variable, directory in directories.items():
                    directory.mkdir(parents=True, exist_ok=True)
                    environment[variable] = str(directory)
                for command in spec["commands"]:
                    step = {"argv": sanitize(command), "exit_code": None, "state": "running"}
                    receipt["commands"].append(step)
                    work.persist(config, unit)
                    try:
                        result = run(command, cwd=tree, env=environment, text=False, timeout=spec["timeout"], check=False)
                    except HubError:
                        step["state"] = "failed"
                        raise
                    step.update(exit_code=result.returncode, state="complete" if result.returncode == 0 else "failed")
                    work.persist(config, unit)
                    if result.returncode:
                        raise HubError(f"Setup command failed (exit {result.returncode})")
                if any(not link["reused"] for link in link_plan(repo, tree, spec["links"], receipt["links"])):
                    raise HubError("Setup link is missing after commands")
                receipt.update(state="complete", ready=True)
            except (HubError, OSError) as exc:
                receipt.update(state="failed", ready=False,
                               problem=str(exc) if isinstance(exc, HubError) else "Setup filesystem operation failed")
            except KeyboardInterrupt:
                if receipt["commands"] and receipt["commands"][-1]["state"] == "running":
                    receipt["commands"][-1]["state"] = "interrupted"
                receipt.update(state="interrupted", ready=False, problem="Setup interrupted; inspect processes and artifacts before retrying")
                work.persist(config, unit)
                raise
            work.persist(config, unit)
            results.append(dict(receipt, name=name))
        ready = None
        if any(r["ready"] is False for r in results):
            ready = False
        elif all(r["ready"] is True for r in results):
            ready = True
        return {"id": identifier, "applied": apply, "ready": ready, "repos": results,
                "readiness": "Configured setup steps only; application checks have not run",
                "cleanup": "Artifacts are retained; setup receipts never authorize deletion"}
