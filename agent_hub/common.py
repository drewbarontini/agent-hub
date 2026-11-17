"""Small filesystem and process primitives shared by the CLI commands."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


class HubError(Exception):
    pass


def redact(value: str) -> str:
    from .security import PATTERNS
    for pattern in PATTERNS:
        value = re.sub(pattern, "[redacted]", value)
    value = re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", value)
    return re.sub(r"(?i)(token|password|secret|api_key)(\s*[=:]\s*)[^\s,]+", r"\1\2[redacted]", value)


def sanitize(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def run(args, cwd=None, *, check=True, timeout=60, text=True):
    try:
        result = subprocess.run([str(x) for x in args], cwd=cwd, text=text,
                                capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HubError(f"Cannot run {Path(str(args[0])).name}: {type(exc).__name__}") from exc
    if check and result.returncode:
        # Command lines and stderr can contain credentials. Keep errors generic.
        raise HubError(f"{Path(str(args[0])).name} failed (exit {result.returncode}); check access and configuration")
    return result


def git(path, *args, check=True):
    return run(["git", "-C", path, *args], check=check).stdout.strip()


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise HubError(f"Refusing symlink output: {path.name}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".hub-write-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(path: Path, data):
    write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise HubError(f"Cannot read valid JSON: {path.name}") from exc


def slug(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise HubError("Names must use 1–80 letters, digits, underscores or hyphens")
    return value


def child(root: Path, *parts) -> Path:
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise HubError("Path escapes its owning directory")
    return target


def toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def remote_id(value: str) -> str:
    if not value or any(c.isspace() for c in value) or value.startswith("-"):
        raise HubError("Invalid repository source")
    if re.search(r"https?://[^/]*@|[?#]", value):
        raise HubError("Repository URLs must not contain credentials, query strings or fragments")
    if value.startswith("git@"):
        value = value[4:].replace(":", "/", 1)
    else:
        value = re.sub(r"^(https?|ssh|git)://", "", value).removeprefix("git@")
    return value.rstrip("/").removesuffix(".git")

