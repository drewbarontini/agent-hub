"""Claude Code adapter.

Native Claude permissions are intentionally distinct from Codex. Worker launches
use restricted mode plus a fail-closed sandbox and an explicit native probe.
"""
from __future__ import annotations

import errno
import json
import re
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

from .common import HubError, git, run, save, write
from .evolution import refresh_instructions
from .repos import executable
from .work import load, location, validate_tree

# Required for blockWritesOutsideWorkingDirectories; older Claude versions may
# ignore this setting. See https://code.claude.com/docs/en/permissions.
MIN_VERSION = (2, 1, 314)


# Narrow execution seam: tests can stub Claude without replacing Git subprocess calls.
def execute(command, **kwargs):
    return subprocess.run(command, **kwargs)


def binary(config):
    tool = executable(config, "claude")
    if not tool:
        raise HubError("Claude Code executable missing; install it or set tools.claude in local.toml")
    result = run([tool, "--version"], check=False)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout or "")
    if result.returncode or not match or tuple(map(int, match.groups())) < MIN_VERSION:
        raise HubError("Claude Code 2.1.314+ required for Hub's restricted Worker file boundary")
    return tool


def edit_deny(path):
    """Claude Edit rules use gitignore patterns; // denotes filesystem-absolute."""
    value = path.resolve().as_posix().lstrip("/")
    value = "".join("\\" + ch if ch in "*?[]" else ch for ch in value)
    return f"Edit(//{value})"


def worker_settings(config, unit):
    """Session-local safeguards; never rewrite native/managed settings."""
    root = location(config, unit["id"])
    denied = [str(root / "AGENTS.md"), str(root / "CLAUDE.md")]
    git_dirs = []
    for name in unit["repos"]:
        path = location(config, unit["id"], name)
        denied.extend(str(path / item) for item in (
            "AGENTS.md", "CLAUDE.md", ".mcp.json", ".git", ".claude",
            ".codex", ".agents", ".aws"))
        common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
        denied.append(str(common))
        git_dirs.append(str(common))
    # The Bash sandbox does not cover Claude's native Edit/Write tools.
    # Deny both exact paths and descendants at the permission layer.
    edit_denials = sorted({rule for name in denied for rule in (
        edit_deny(Path(name)), edit_deny(Path(name))[:-1] + "/**)")})
    # Linked worktrees can have shared Git metadata outside the work-unit root.
    # Additional directories allow read access under blockReadsOutsideWorkingDirectories;
    # both Bash and native Edit remain explicitly write-denied above.
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": True,
            "filesystem": {"disabled": False, "denyWrite": sorted(set(denied))},
            "network": {"allowedDomains": []},
        },
        "permissions": {
            "blockReadsOutsideWorkingDirectories": True,
            "blockWritesOutsideWorkingDirectories": True,
            "additionalDirectories": sorted(set(git_dirs)),
            "allow": ["Read", "Write", "Edit"],
            "deny": ["WebFetch", "WebSearch", "mcp__*", *edit_denials,
                     "Bash(git commit *)", "Bash(git push *)", "Bash(git reset *)",
                     "Bash(git checkout *)", "Bash(git switch *)"],
        },
    }


def plan(config, role, identifier=None):
    tool = binary(config)
    if role == "orchestrator":
        refresh_instructions(config)
        return {
            "command": [
                tool, "--permission-mode", "plan", "--tools", "Read,Glob,Grep",
                "Read AGENTS.md and .hub/ORCHESTRATOR.md. Review the configured work board and available context with me. Do not assume implementation intent or mutate Hub state.",
            ],
            "cwd": str(config.root), "role": role,
            "permissions": "read-only built-in tools, plan mode; native MCP/connector permissions remain provider-managed",
            "limitations": "Native Claude settings and MCP tools are not an OS-level sandbox; verify integrations independently",
        }
    unit = load(config, identifier)
    if unit["status"] not in {"prepared", "review"}:
        raise HubError("Prepare work before launching a Worker")
    for name in unit["repos"]:
        validate_tree(config, unit, name)
    root = location(config, identifier)
    if not (root / "AGENTS.md").is_file():
        raise HubError("Worker instructions missing; prepare work first")
    prompt = ("Read AGENTS.md and each relevant repository's own instructions. "
              "Use only the explicitly available context and skills to complete the bounded task. "
              "Run appropriate checks, write outcome.md with actual evidence and unresolved issues. "
              "Do not commit, push, change branches, or make external changes.")
    command = [
        tool, "--restricted", "--permission-mode", "dontAsk",
        "--tools", "Bash,Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "mcp__*", "--no-chrome",
        "--settings", json.dumps(worker_settings(config, unit), separators=(",", ":")),
        prompt,
    ]
    return {
        "command": command, "cwd": str(root), "role": role, "id": identifier,
        "permissions": "Claude restricted mode; native fail-closed command sandbox; no network or MCP; files scoped to work unit",
        "limitations": "Claude skills and connectors require explicit availability; native sandbox and file-tool protections are different from Codex and must be probed",
    }


def sandbox_probe(config, identifier):
    """Cost-incurring native Bash probe through Claude. Fail closed on any ambiguity.

    Claude has no documented model-free CLI sandbox command. We ask a bounded
    Claude -p session to run a disposable script with Bash and verify the results
    on disk ourselves. No successful tool execution => no Worker launch.
    """
    unit = load(config, identifier)
    root = location(config, identifier)
    for name in unit["repos"]:
        validate_tree(config, unit, name)
    tool = binary(config)
    ident = uuid.uuid4().hex
    outside = config.root / ".hub/sandbox-probes" / (ident + ".txt")
    script = root / (".hub-probe-" + ident + ".py")
    output = root / (".hub-probe-" + ident + ".json")
    marker = root / (".hub-probe-" + ident + ".txt")
    write(outside, "untouched\n")
    protected = [str(outside)] + [str(location(config, identifier, name) / ".git") for name in unit["repos"]]
    protected += [str(Path(git(location(config, identifier, name), "rev-parse", "--path-format=absolute", "--git-common-dir")) / "HEAD") for name in unit["repos"]]
    source = (
        "import errno,json,pathlib\n"
        f"marker=pathlib.Path({str(marker)!r})\n"
        f"result=pathlib.Path({str(output)!r})\n"
        f"paths={protected!r}\n"
        "marker.write_text('inside')\n"
        "inside=marker.read_text()=='inside'\n"
        "marker.unlink()\n"
        "blocked=[]\n"
        "for path in paths:\n"
        " try:\n"
        "  with open(path,'r+'): pass\n"
        "  blocked.append(False)\n"
        " except OSError as exc:\n"
        "  blocked.append(exc.errno in (errno.EACCES,errno.EPERM,errno.EROFS))\n"
        "result.write_text(json.dumps({'inside_write':inside,'outside_and_metadata_blocked':blocked}))\n"
    )
    write(script, source)
    passed = False
    detail = {"reason": "Claude did not demonstrate required native filesystem isolation"}
    code = 1
    try:
        settings = json.dumps(worker_settings(config, unit), separators=(",", ":"))
        command = [tool, "--restricted", "--permission-mode", "dontAsk",
                   "--tools", "Bash", "--disallowedTools", "mcp__*",
                   "--settings", settings,
                   "--print", "--output-format", "json",
                   "Use the Bash tool to execute exactly this command once, then stop: "
                   + shlex.quote(sys.executable) + " " + shlex.quote(str(script))]
        try:
            result = execute(command, cwd=root, capture_output=True, text=True, timeout=180)
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired):
            code = 1
        if code == 0 and output.is_file() and not output.is_symlink():
            try:
                data = json.loads(output.read_text())
                blocked = data.get("outside_and_metadata_blocked")
                passed = (data.get("inside_write") is True and isinstance(blocked, list)
                          and len(blocked) == len(protected) and all(v is True for v in blocked)
                          and outside.read_text() == "untouched\n")
                detail = data if passed else {"reason": "Native boundary probe checks did not pass"}
            except (OSError, ValueError, AttributeError):
                pass
        report = {"passed": passed, "exit_code": 0 if passed else (code or 1),
                  "checks": detail, "runtime": "claude",
                  "scope": "native Bash/filesystem boundary; MCPs disabled; model-assisted probe (may incur charges)"}
        save(config.root / ".hub/last-claude-sandbox-probe.json", report)
        return report
    finally:
        for path in (outside, script, output, marker):
            path.unlink(missing_ok=True)
