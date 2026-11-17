from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .common import CORE, HubError, git, redact, run, save, sanitize
from .config import Config
from . import agents, context, evolution, repos, security, work


def parser():
    p = argparse.ArgumentParser(description="Agent Hub — one core, many contexts, independent ownership")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--instance", default=".", help="Instance root (default current directory)")
    commands = p.add_subparsers(dest="command", required=True)
    q = commands.add_parser("init", help="Initialize an independent Instance (after proposal approval)")
    q.add_argument("destination")
    q.add_argument("--name", required=True)
    q.add_argument("--core-source", default=str(CORE))
    q.add_argument("--ref", default="HEAD")
    q.add_argument("--purpose", default="Coordinate intentional work")
    q.add_argument("--public-source", default=evolution.PUBLIC_SOURCE)
    q = commands.add_parser("discover", help="Inspect only explicitly authorized project roots")
    q.add_argument("--root", action="append", required=True)
    q.add_argument("--depth", type=int, default=2)
    for name in ["config-check", "bootstrap", "status", "workspace", "doctor", "resources"]:
        commands.add_parser(name)
    q = commands.add_parser("context", help="View or regenerate the Instance Context Index")
    q.add_argument("--section", choices=["summary", "resources", "repositories"], default="summary")
    q.add_argument("--write", action="store_true", help="Regenerate ignored navigation files under .hub/")
    q = commands.add_parser("inventory", help="Inspect known instruction and skill files in registered repositories")
    q.add_argument("--repo", action="append", help="Restrict to a named registered repository; repeat as needed")
    q = commands.add_parser("guard-check")
    q.add_argument("--branch", required=True)
    q.add_argument("--push", action="store_true")
    q = commands.add_parser("guard-install", help="Explicitly install hooks; refuses existing hooks")
    q.add_argument("repo")
    q = commands.add_parser("work")
    sub = q.add_subparsers(dest="action", required=True)
    for action in ("create", "start"):
        r = sub.add_parser(action, help="Create and prepare, or resume bounded work" if action == "start" else "Create an execution record")
        if action == "start":
            r.add_argument("reference", nargs="?", help="Execution ID or unambiguous human source key")
        for option in ("title", "intent", "verify"):
            r.add_argument("--" + option, required=action == "create")
        scope = r.add_mutually_exclusive_group()
        scope.add_argument("--repo", action="append", default=[] if action == "create" else None)
        if action == "start":
            scope.add_argument("--no-repos", action="store_true", help="Explicitly scope non-code work")
        r.add_argument("--resource", action="append", default=[] if action == "create" else None)
        r.add_argument("--source-provider", default="manual" if action == "create" else None)
        r.add_argument("--source-id")
        r.add_argument("--source-key", help="Human ticket key used in branch names; distinct from immutable source ID")
        r.add_argument("--source-url")
    for name in ["prepare", "status", "cleanup", "report", "release"]:
        r = sub.add_parser(name)
        r.add_argument("id")
        if name == "cleanup":
            r.add_argument("--apply", action="store_true")
        if name == "report":
            r.add_argument("--summary", required=True)
            r.add_argument("--verification")
        if name == "release":
            r.add_argument("--session", required=True)
            r.add_argument("--ack-session-ended", action="store_true", required=True)
    q = commands.add_parser("agent")
    q.add_argument("role", choices=["orchestrator", "worker"])
    q.add_argument("id", nargs="?")
    q.add_argument("--launch", action="store_true", help="Actually run; default prints a launch plan")
    q.add_argument("--noninteractive", action="store_true")
    q = commands.add_parser("sandbox-check", help="Probe Worker write boundary without a model call")
    q.add_argument("id")
    q = commands.add_parser("adopt")
    q.add_argument("--source")
    q.add_argument("--ref", required=True)
    q.add_argument("--apply", action="store_true", help="Approve candidate code execution, tests and lock switch")
    commands.add_parser("rollback")
    q = commands.add_parser("reconcile", help="Read-only structured assessment; inspect no source implementation")
    q.add_argument("--inventory")
    q = commands.add_parser("promote", help="Prepare prose proposal; never export implementation files")
    q.add_argument("--problem", required=True)
    q.add_argument("--requirement", required=True)
    q.add_argument("--ownership", choices=["unknown", "personal", "organization", "approved-for-public"], default="unknown")
    q.add_argument("--disclosure-authorized", action="store_true")
    q = commands.add_parser("service", help="Inspect or explicitly run a named foreground service")
    q.add_argument("name")
    q.add_argument("--run", action="store_true")
    q.add_argument("--allow-sensitive", action="store_true")
    q = commands.add_parser("secrets")
    q.add_argument("--staged", action="store_true")
    return p


def service(config, name, execute=False, allow_sensitive=False):
    item = next((x for x in config.resources if x["name"] == name and x["kind"] == "service"), None)
    if not item or not item.get("command"):
        raise HubError("Unknown service or missing command array")
    cwd = config.repo(item["repo"])["path"] if "repo" in item else config.path(item.get("path", "."))
    missing = [key for key in item.get("environment", []) if key not in os.environ]
    plan = {"name": name, "cwd": str(cwd), "command": item["command"], "missing_environment": missing,
            "autostart": "disabled in v0.1", "preview_url": item.get("preview_url"),
            "logs": "foreground terminal; process exit status is reported"}
    if execute:
        if missing:
            raise HubError("Service environment requirements are missing (values withheld)")
        if item.get("sensitive", True) and not allow_sensitive:
            raise HubError("Sensitive or unclassified service requires --allow-sensitive")
        if "repo" in item:
            repos.available(config.repo(item["repo"]))
        plan["exit_code"] = subprocess.run(item["command"], cwd=cwd).returncode
    return plan


def dispatch(args):
    command = args.command
    if command == "init":
        return evolution.init(args.destination, args.name, args.core_source, args.ref, args.purpose, args.public_source)
    if command == "discover":
        return repos.discover(args.root, args.depth)
    if command == "guard-check":
        repos.guard(Path.cwd(), args.branch)
        if args.push:
            for line in sys.stdin:
                fields = line.split()
                if len(fields) != 4:
                    raise HubError("Malformed pre-push input")
                if fields[2] == "refs/heads/" + args.branch:
                    raise HubError("Push targets protected default branch")
        return {"allowed": True}
    if command == "secrets":
        return security.scan(Path.cwd(), args.staged)
    config = Config(args.instance)
    if command == "config-check":
        return {"valid": True, "schema_version": 1, "repositories": len(config.repos), "resources": len(config.resources)}
    if command == "bootstrap":
        return repos.bootstrap(config)
    if command == "status":
        return {"repositories": [repos.inspect(r) for r in config.repos.values()], "work": work.status(config)}
    if command == "workspace":
        return repos.workspace(config)
    if command == "doctor":
        return repos.doctor(config)
    if command == "resources":
        return repos.resources(config)
    if command == "context":
        if args.write:
            result = context.write_index(config)
            return dict(result, catalog=context.catalog(config, args.section))
        return context.catalog(config, args.section)
    if command == "inventory":
        return context.inventory(config, args.repo)
    if command == "guard-install":
        return repos.install_guard(config, args.repo)
    if command == "work":
        if args.action in {"create", "start"}:
            source = {field: getattr(args, "source_" + field) for field in ("provider", "id", "key", "url")
                      if getattr(args, "source_" + field) is not None}
            if args.action == "start":
                return work.start(config, args.reference, title=args.title, intent=args.intent,
                                  names=[] if args.no_repos else args.repo, verification=args.verify,
                                  source=source, resource_names=args.resource)
            return work.create(config, args.title, args.intent, args.repo, args.verify, source, args.resource)
        args.id = work.resolve(config, args.id)
        if args.action == "prepare":
            return work.prepare(config, args.id)
        if args.action == "status":
            return work.status(config, args.id)
        if args.action == "cleanup":
            return work.cleanup(config, args.id, args.apply)
        if args.action == "report":
            return work.report(config, args.id, args.summary, args.verification)
        return work.release(config, args.id, args.session)
    if command == "agent":
        if args.role == "worker" and not args.id:
            raise HubError("Worker requires a work-unit ID")
        if args.role == "worker":
            args.id = work.resolve(config, args.id)
        return agents.launch(config, args.role, args.id, args.noninteractive) if args.launch else agents.plan(config, args.role, args.id)
    if command == "sandbox-check":
        return agents.sandbox_probe(config, work.resolve(config, args.id))
    if command == "adopt":
        source = args.source or config.data.get("core", {}).get("source", config.lock["source"])
        return evolution.adopt(config, source, args.ref, args.apply)
    if command == "rollback":
        return evolution.rollback(config)
    if command == "reconcile":
        return evolution.reconcile(config, args.inventory)
    if command == "promote":
        return evolution.promote(config, args.problem, args.requirement, args.ownership, args.disclosure_authorized)
    if command == "service":
        return service(config, args.name, args.run, args.allow_sensitive)
    raise HubError("Unknown command")


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        result = dispatch(args)
        print(json.dumps(sanitize(result), indent=2, default=str))
        failed = isinstance(result, dict) and (result.get("ready") is False or result.get("passed") is False or
                                               result.get("exit_code", 0) not in (0, None))
        if failed:
            raise SystemExit(1)
    except (HubError, OSError, ValueError, KeyError, TypeError) as exc:
        # Do not leak configuration values or subprocess output in diagnostics.
        message = str(exc) if isinstance(exc, HubError) else f"Invalid input or inaccessible resource ({type(exc).__name__})"
        print(json.dumps({"error": redact(message)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
