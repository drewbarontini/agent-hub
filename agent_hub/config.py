from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .common import HubError, child, remote_id, slug


def load_toml(path, optional=False):
    if optional and not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HubError(f"Cannot read valid TOML: {path.name}") from exc


def merge(base, extra):
    result = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        elif key == "resources" and isinstance(value, list):
            entries = {x["name"]: x for x in result.get(key, [])}
            for item in value:
                entries[item["name"]] = merge(entries.get(item["name"], {}), item)
            result[key] = list(entries.values())
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        shared = load_toml(self.root / "hub.toml")
        local = load_toml(self.root / "local.toml", optional=True)
        overlay = local.get("overlay") or os.environ.get("HUB_OVERLAY")
        self.data = shared
        if overlay:
            p = Path(overlay).expanduser()
            if not p.is_absolute():
                p = self.root / p
            self.data = merge(shared, load_toml(p))
        self.data = merge(self.data, local)
        if self.data.get("schema_version") != 1:
            raise HubError("Unsupported hub schema_version (expected 1)")
        instance = self.data.get("instance", {})
        slug(instance.get("name", ""))
        self.runtime = self.data.get("agent", {}).get("runtime", "codex")
        if self.runtime not in {"codex", "claude"}:
            raise HubError("agent.runtime must be codex or claude")
        repos = load_toml(self.root / "repos.toml").get("repos", [])
        if not isinstance(repos, list):
            raise HubError("repos.toml must contain [[repos]] entries")
        self.repos = {}
        paths = self.data.get("paths", {})
        self.repos_root = self.path(paths.get("repos_root", "../"))
        for source in repos:
            repo = dict(source)
            name = slug(repo.get("name", ""))
            if name in self.repos:
                raise HubError(f"Duplicate repository: {name}")
            remote_id(repo.get("remote", ""))
            branch = repo.get("default_branch", "main")
            if branch.startswith("-") or not branch or any(c in branch for c in " ~^:?*[\\"):
                raise HubError(f"Invalid default branch: {name}")
            for flag, default in [("protected", True), ("checkout", False), ("visible", True)]:
                repo.setdefault(flag, default)
                if not isinstance(repo[flag], bool):
                    raise HubError(f"{name}.{flag} must be a boolean")
            repo["default_branch"] = branch
            local_repo = self.data.get("repos", {}).get(name, {})
            if "path" in local_repo:
                repo["path"] = self.path(local_repo["path"])
            else:
                repo["path"] = child(self.repos_root, repo.get("folder", name))
            self.repos[name] = repo
        destinations = [r["path"].resolve() for r in self.repos.values()]
        if len(set(destinations)) != len(destinations):
            raise HubError("Repositories must have distinct local paths")
        if any(a.is_relative_to(b) or b.is_relative_to(a)
               for i, a in enumerate(destinations) for b in destinations[i + 1:]):
            raise HubError("Nested managed repositories are unsupported")
        self.resources = self.data.get("resources", [])
        names = set()
        for item in self.resources:
            name = slug(item.get("name", ""))
            if name in names:
                raise HubError(f"Duplicate resource: {name}")
            names.add(name)
            if item.get("kind") not in {"context", "capability", "tool", "mcp", "work", "service"}:
                raise HubError(f"Invalid resource kind: {name}")
            if "command" in item:
                command = item["command"]
                if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                    raise HubError(f"{name}.command must be a nonempty string array")
            if "repo" in item and item["repo"] not in self.repos:
                raise HubError(f"Unknown repository on resource: {name}")
        self.lock = load_lock(self.root)

    def path(self, value):
        p = Path(value).expanduser()
        return (self.root / p).resolve() if not p.is_absolute() else p.resolve()

    def repo(self, name):
        if name not in self.repos:
            raise HubError(f"Unregistered repository: {name}")
        return self.repos[name]


def load_lock(root):
    from .common import read_json
    lock = read_json(root / "core.lock")
    import re
    if lock.get("schema_version") != 1 or not re.fullmatch(r"[0-9a-f]{40}", lock.get("commit", "")):
        raise HubError("Invalid Core lock")
    remote_id(lock.get("source", ""))
    return lock
