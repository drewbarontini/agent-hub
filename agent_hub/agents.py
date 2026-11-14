from __future__ import annotations

import subprocess
import uuid
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path

from .common import HubError, git, run, save, write
from .evolution import refresh_instructions
from .repos import executable
from .work import load, location, mutation, now, persist, validate_tree


def execute(command, **kwargs):
    return subprocess.run(command, **kwargs)


def check_native_config(root):
    """Refuse legacy config that can override named permission selection.

    Only parse provider configuration, never auth files. Do not display values.
    Hub does not rewrite user, project or managed runtime configuration.
    """
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    paths = [home / "config.toml", Path("/etc/codex/config.toml")]
    paths += [p / ".codex/config.toml" for p in [root, *root.parents]]
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open("rb") as stream:
                data = tomllib.load(stream)
        except (OSError, ValueError):
            raise HubError("Cannot validate native Codex configuration; no Worker launch")
        if "sandbox_mode" in data or "sandbox_workspace_write" in data:
            raise HubError("Native Codex config uses legacy sandbox settings that can override named permissions; reconcile native config before Worker launch")


def permission_args(config, role, root, unit=None):
    """Explicit named policy: no inherited writable roots or writable temp trees."""
    name = "hub-" + hashlib.sha256((str(root) + role).encode()).hexdigest()[:12]
    filesystem = {":root": "read"}
    if role == "worker":
        filesystem[str(root)] = "write"
        for name_in_unit in unit["repos"]:
            p = location(config, unit["id"], name_in_unit)
            for protected in [".git", ".codex", ".agents", ".aws"]:
                filesystem[str(p / protected)] = "read"
            common_dir = git(p, "rev-parse", "--path-format=absolute", "--git-common-dir")
            filesystem[common_dir] = "read"
        filesystem[str(root / "AGENTS.md")] = "read"
        filesystem[str(root / "CLAUDE.md")] = "read"
    # JSON string syntax also encodes TOML basic strings safely.
    encoded = "{" + ",".join(json.dumps(k) + "=" + json.dumps(v) for k, v in filesystem.items()) + "}"
    policy = "{filesystem=" + encoded + ",network={enabled=false}}"
    return ["-c", "default_permissions=" + json.dumps(name), "-c", f"permissions.{name}={policy}"]


def sandbox_probe(config, identifier):
    """Execute no model calls and touch only disposable Hub-owned sentinel files."""
    unit = load(config, identifier)
    root = location(config, identifier)
    check_native_config(root)
    for name in unit["repos"]:
        validate_tree(config, unit, name)
    binary = executable(config, "codex")
    if not binary:
        raise HubError("Codex executable unavailable")
    outside = config.root / ".hub/sandbox-probes" / (uuid.uuid4().hex + ".txt")
    write(outside, "owned probe; leave unchanged\n")
    inside = root / (".sandbox-probe-" + uuid.uuid4().hex)
    protected = [str(outside)] + [str(location(config, identifier, n) / ".git") for n in unit["repos"]]
    code = ("import json,pathlib\n"
            f"inside=pathlib.Path({str(inside)!r})\n"
            "inside.write_text('probe'); inside.unlink()\n"
            "blocked=[]\n"
            f"for name in {protected!r}:\n"
            " try:\n"
            "  with open(name,'r+'): pass\n"
            "  blocked.append(False)\n"
            " except PermissionError: blocked.append(True)\n"
            "print(json.dumps({'inside_write':True,'outside_and_metadata_blocked':blocked}))\n"
            "raise SystemExit(0 if all(blocked) else 2)\n")
    options = permission_args(config, "worker", root, unit)
    profile_name = json.loads(options[1].split("=", 1)[1])
    command = [binary, "sandbox", "--permission-profile", profile_name] + options + ["--cd", str(root), sys.executable, "-c", code]
    try:
        result = run(command, check=False)
        passed = result.returncode == 0
        detail = json.loads(result.stdout) if passed else {"reason": "Runtime cannot enforce or execute the requested sandbox on this host"}
        report = {"passed": passed, "exit_code": result.returncode, "checks": detail,
                  "runtime": run([binary, "--version"], check=False).stdout.strip(),
                  "scope": "local filesystem command boundary; excludes MCPs, connectors and native editor sessions"}
        save(config.root / ".hub/last-sandbox-probe.json", report)
        return report
    finally:
        outside.unlink(missing_ok=True)
        inside.unlink(missing_ok=True)


def plan(config, role, identifier=None):
    if config.runtime != "codex":
        raise HubError("Claude launch is not implemented/tested; see docs/agents.md for the compatibility path")
    binary = executable(config, "codex")
    if not binary:
        raise HubError("Codex executable missing; install the CLI or set tools.codex in local.toml")
    if role == "orchestrator":
        refresh_instructions(config)
        return {"command": [binary, "--cd", str(config.root)] + permission_args(config, role, config.root) + [
                             "--ask-for-approval", "never",
                             "Read AGENTS.md and .hub/ORCHESTRATOR.md. Inspect work status. Ask how I want to proceed; do not assume implementation intent."],
                "cwd": str(config.root), "role": role,
                "permissions": "read-only; operator performs authorized lifecycle changes separately"}
    unit = load(config, identifier)
    if unit["status"] not in {"prepared", "review"}:
        raise HubError("Prepare work before launching a Worker")
    for name in unit["repos"]:
        validate_tree(config, unit, name)
    root = location(config, identifier)
    if not (root / "AGENTS.md").is_file():
        raise HubError("Worker instructions missing; prepare work first")
    args = [binary, "--cd", str(root), "--ask-for-approval", "never"] + permission_args(config, role, root, unit)
    prompt = "Read AGENTS.md in this work unit, then repository-specific instructions. Execute only the bounded intent. Write outcome.md with changes, actual verification results, and unresolved issues. Do not commit or change branches."
    return {"command": args + [prompt], "cwd": str(root), "role": role, "id": identifier,
            "permissions": "workspace-write limited to this work unit; no approval escalation; Git metadata is protected by the runtime",
            "limitations": "Runtime inherited configuration, MCPs and read access are not a confidentiality boundary"}


def launch(config, role, identifier=None, noninteractive=False):
    launch_plan = plan(config, role, identifier)
    command = launch_plan["command"]
    if role == "worker" and not sandbox_probe(config, identifier)["passed"]:
        raise HubError("Worker launch blocked: sandbox probe failed; no unsandboxed fallback. See .hub/last-sandbox-probe.json")
    if noninteractive:
        # Subcommand-specific options precede the final prompt.
        command = command[:-1] + ["exec", "--ignore-user-config", "--json", command[-1]]
    session_id = uuid.uuid4().hex
    if role == "worker":
        with mutation(config):
            unit = load(config, identifier)
            if any(s["status"] == "running" for s in unit["sessions"]):
                raise HubError("This work unit already has an active session")
            unit["sessions"].append({"id": session_id, "runtime": "codex", "status": "running", "started_at": now()})
            persist(config, unit)
    log = config.root / ".hub/session-logs" / (session_id + ".jsonl")
    exit_code = None
    try:
        if noninteractive:
            log.parent.mkdir(parents=True, exist_ok=True)
            # Persist event types only; provider payloads and stderr may contain secrets.
            result = execute(command, cwd=launch_plan["cwd"], capture_output=True, text=True, timeout=600)
            known_events = {"thread.started", "turn.started", "turn.completed", "turn.failed",
                            "item.started", "item.updated", "item.completed", "error"}
            with log.open("x") as stream:
                for line in (result.stdout or "").splitlines():
                    try:
                        event = json.loads(line)
                    except (ValueError, RecursionError):
                        continue
                    if isinstance(event, dict) and event.get("type") in known_events:
                        stream.write(json.dumps({"type": event["type"]}) + "\n")
                stream.write(json.dumps({"exit_code": result.returncode}) + "\n")
        else:
            result = execute(command, cwd=launch_plan["cwd"])
        exit_code = result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HubError(f"Agent launch failed: {type(exc).__name__}; inspect local session logs") from exc
    finally:
        if role == "worker":
            with mutation(config):
                unit = load(config, identifier)
                session = next(s for s in unit["sessions"] if s["id"] == session_id)
                session.update(status="finished" if exit_code == 0 else "interrupted", ended_at=now(), exit_code=exit_code)
                persist(config, unit)
    return {"session": session_id, "exit_code": exit_code,
            "log": str(log) if noninteractive else "interactive terminal; native runtime owns session history"}

