from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .common import CORE, HubError, git, read_json, remote_id, run, save, slug, toml_string, write
from .config import Config, load_toml
from .repos import doctor, workspace
from .work import mutation, now

PUBLIC_SOURCE = "https://github.com/drewbarontini/agent-hub.git"


def resolve(source, ref):
    remote_id(str(source))
    if str(ref).startswith("-"):
        raise HubError("Invalid Core ref")
    p = Path(source).expanduser()
    if p.exists():
        return git(p, "rev-parse", "--verify", str(ref) + "^{commit}")
    rows = run(["git", "ls-remote", "--", str(source), str(ref), "refs/tags/" + ref,
                "refs/tags/" + ref + "^{}", "refs/heads/" + ref]).stdout.splitlines()
    commits = [line.split()[0] for line in rows if line.strip()]
    if not commits:
        # A full SHA is reproducible even when ls-remote cannot advertise it.
        import re
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            return ref
        raise HubError("Core ref was not found")
    peeled = [line.split()[0] for line in rows if line.endswith("^{}")]
    values = set(peeled or commits)
    if len(values) != 1:
        raise HubError("Ambiguous Core ref; use a full commit")
    return values.pop()


def install(root, source, commit):
    from .common import child
    target = child(root, ".hub", "cores", commit)
    if target.exists():
        if git(target, "rev-parse", "HEAD") != commit or git(target, "status", "--porcelain", "--untracked-files=all"):
            raise HubError("Installed Core checkout is modified or has the wrong commit")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--no-hardlinks", "--no-checkout", "--", str(source), target])
    run(["git", "-C", target, "checkout", "--detach", commit])
    if not (target / "bin/hub").is_file() or not (target / "agent_hub/cli.py").is_file():
        raise HubError("Source is not a compatible Agent Hub Core")
    return target


def init(root, name, source, ref="HEAD", purpose="Coordinate intentional work", public_source=PUBLIC_SOURCE):
    root = Path(root).expanduser().resolve()
    if root == CORE or root.is_relative_to(CORE):
        raise HubError("Create the Instance outside the Core checkout")
    slug(name)
    remote_id(public_source)
    root.mkdir(parents=True, exist_ok=True)
    if (root / "hub.toml").exists():
        config = Config(root)
        local_source = config.data.get("core", {}).get("source", config.lock["source"])
        install(root, local_source, config.lock["commit"])
        refresh_instructions(config)
        workspace(config)
        return {"instance": str(root), "created": False, "configuration": "preserved"}
    if any(root.iterdir()):
        raise HubError("New Instance destination must be empty; use reconciliation for an existing Hub")
    # Verify a commit exists before writing configuration.
    commit = resolve(source, ref)
    install(root, source, commit)
    run(["git", "init", "-b", "main", root])
    write(root / ".gitignore", ".hub/\nlocal.toml\n*.code-workspace\n.env\n.env.*\n!.env.example\n__pycache__/\n.DS_Store\n")
    write(root / "hub.toml", f"schema_version = 1\n\n[instance]\nname = {toml_string(name)}\npurpose = {toml_string(purpose)}\n\n[agent]\nruntime = \"codex\"\n\n# Register resources with [[resources]]. See Core docs/configuration.md.\n")
    write(root / "repos.toml", "# [[repos]] entries describe repositories; paths resolve locally.\nrepos = []\n")
    source_path = Path(source).expanduser()
    if source_path.exists():
        write(root / "local.toml", f"[core]\nsource = {toml_string(source_path.resolve())}\n\n[paths]\nrepos_root = \"../\"\n")
    save(root / "core.lock", {"schema_version": 1, "source": public_source, "commit": commit, "version": "0.1.0"})
    write(root / "AGENTS.md", "# Hub Instance\n\nRead `.hub/ORCHESTRATOR.md` for the active Core operating instructions.\nRead `instructions.md` if present for Instance-specific guidance.\nStrategic exploration does not authorize implementation or task creation.\nDo not publish context, configuration, or Instance-derived improvements without approval.\n")
    write(root / "CLAUDE.md", "@AGENTS.md\n")
    refresh_instructions(Config(root))
    workspace(Config(root))
    return {"instance": str(root), "created": True, "commit": commit,
            "next": "Review and configure repositories and resources, then run bootstrap and doctor"}


def refresh_instructions(config):
    from .common import child
    core = config.root / ".hub/cores" / config.lock["commit"]
    prompt = (core / "prompts/orchestrator.md").read_text()
    write(config.root / ".hub/ORCHESTRATOR.md", prompt + "\nInstance: " + config.data["instance"]["name"] +
          "\nCore commit: " + config.lock["commit"] + "\n")
    launchers = child(config.root, ".hub", "bin")
    launchers.mkdir(parents=True, exist_ok=True)
    entry = launchers / "hub"
    if entry.exists() and not entry.is_symlink():
        raise HubError("Refusing to replace non-symlink Hub entry point")
    replacement = launchers / ".hub-next"
    if replacement.exists() or replacement.is_symlink():
        raise HubError("Ambiguous pending Hub entry point")
    replacement.symlink_to(core / "bin/hub")
    replacement.replace(entry)


def adoption_plan(config, source, ref):
    commit = resolve(source, ref)
    # Use an existing checkout for an inspectable plan. No target code is run.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="hub-adopt-inspect-") as tmp:
        run(["git", "clone", "--no-checkout", "--", str(source), tmp])
        version = git(tmp, "show", f"{commit}:pyproject.toml")
        import tomllib
        parsed = tomllib.loads(version)
        current = config.lock["commit"]
        known = run(["git", "-C", tmp, "cat-file", "-e", current + "^{commit}"], check=False).returncode == 0
        changes = git(tmp, "log", "--format=%h %s", current + ".." + commit) if known else "Current commit absent from candidate source; histories may differ"
        schema_text = git(tmp, "show", f"{commit}:templates/instance/hub.toml")
        candidate_schema = tomllib.loads(schema_text).get("schema_version")
        conflicts = []
        if candidate_schema != config.data["schema_version"]:
            conflicts.append("Instance schema migration required")
        if not known:
            conflicts.append("Unrelated or incomplete history; cannot safely summarize adoption")
        return {"current": current, "candidate": commit, "version": parsed["project"]["version"],
                "compatible": not conflicts, "conflicts": conflicts, "changes": changes.splitlines(),
                "instance_changes": "none; shared config and overlays are never rewritten",
                "verification": "candidate test suite, configuration and repository diagnostics",
                "rollback": "previous lock and installed checkout retained"}


def adopt(config, source, ref, apply=False):
    plan = adoption_plan(config, source, ref)
    if not apply:
        return plan
    if not plan["compatible"]:
        raise HubError("Adoption conflicts require manual review before applying")
    with mutation(config):
        if Config(config.root).lock != config.lock:
            raise HubError("Core lock changed while preparing adoption; inspect the new version and retry")
        # Candidate code execution is opt-in through --apply, after reviewing source.
        checkout = install(config.root, source, plan["candidate"])
        if not (checkout / "tests").is_dir() or not list((checkout / "tests").glob("test*.py")):
            raise HubError("Candidate has no validation tests")
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=checkout, timeout=60)
        # Run the candidate CLI too; require it to parse the existing Instance config.
        run([sys.executable, checkout / "bin/hub", "--instance", config.root, "config-check"])
        before = doctor(config)
        if not before["ready"]:
            raise HubError("Current Instance diagnostics must pass before adoption")
        previous = dict(config.lock)
        save(config.root / ".hub/previous-core.lock", previous)
        new_lock = {**previous, "commit": plan["candidate"], "version": plan["version"]}
        save(config.root / "core.lock", new_lock)
        try:
            refreshed = Config(config.root)
            # Ensure generated tasks point at the newly adopted checkout.
            run([sys.executable, checkout / "bin/hub", "--instance", config.root, "workspace"])
            run([sys.executable, checkout / "bin/hub", "--instance", config.root, "doctor"])
            refresh_instructions(refreshed)
        except Exception:
            save(config.root / "core.lock", previous)
            old = config.root / ".hub/cores" / previous["commit"]
            run([sys.executable, old / "bin/hub", "--instance", config.root, "workspace"])
            raise
    return {**plan, "applied": True}


def rollback(config):
    with mutation(config):
        previous = read_json(config.root / ".hub/previous-core.lock")
        checkout = config.root / ".hub/cores" / previous["commit"]
        if git(checkout, "rev-parse", "HEAD") != previous["commit"] or git(checkout, "status", "--porcelain"):
            raise HubError("Rollback Core is missing or modified")
        run([sys.executable, checkout / "bin/hub", "--instance", config.root, "config-check"])
        current = config.lock
        save(config.root / "core.lock", previous)
        save(config.root / ".hub/previous-core.lock", current)
        run([sys.executable, checkout / "bin/hub", "--instance", config.root, "workspace"])
        refresh_instructions(Config(config.root))
        return {"rolled_back_to": previous["commit"]}


CAPABILITIES = {
    "bootstrap": "Identity-checked clone or attachment from repos.toml",
    "worktrees": "One work unit with multiple isolated repository worktrees",
    "workspace": "Generated VS Code multi-root workspace and explicit process tasks",
    "status": "Repository availability and durable work-unit inspection",
    "guard-main": "Worker sandbox, protected-branch validation, optional Git hooks",
    "services": "Explicit foreground service execution; no automatic startup",
    "context": "References and local existence checks; no context ingestion",
    "updates": "Pinned Core adoption, validation and rollback",
}


def reconcile(config, inventory=None):
    # Only read the supplied structured inventory, never the implementation it describes.
    data = load_toml(Path(inventory).expanduser()) if inventory else {}
    items = data.get("capabilities", [])
    rows = []
    seen = set()
    for item in items:
        name = item["name"]
        seen.add(name)
        classification = "Adopt" if name in CAPABILITIES else "Preserve"
        if item.get("obsolete", False) and name in CAPABILITIES:
            classification = "Retire"
        elif item.get("generalizable", False) and name not in CAPABILITIES:
            classification = "Promote candidate"
        rows.append({"capability": name, "current": item.get("description", "Inventory lacks details"),
                     "core": CAPABILITIES.get(name, "No implemented equivalent"), "classification": classification,
                     "ownership": item.get("ownership", "unknown; disclosure review required"),
                     "conflicts": item.get("conflicts", "Requires operational validation"),
                     "provider": item.get("provider", config.runtime),
                     "verification": "Validate on a disposable Instance before retiring existing behavior"})
    for name in sorted(CAPABILITIES.keys() - seen):
        rows.append({"capability": name, "current": "not inventoried", "core": CAPABILITIES[name],
                     "classification": "Adopt", "verification": "Establish existing behavior before migration"})
    return {"read_only": True, "evidence": "authorized inventory only" if inventory else "Instance configuration only; existing implementation not inspected",
            "core_commit": config.lock["commit"], "differences": rows,
            "provider_concerns": ["Codex launch adapter implemented; verify local sandbox enforcement",
                                  "Claude native hooks, permissions, MCP and session launch require separate validation"],
            "privacy": "Keep private repos, Linear, Data Desk and personal context references with their owner",
            "migration_sequence": ["Inventory and authorize inspection", "Preserve existing Hub and record its commit",
                                   "Initialize independent Instance using pinned Core", "Translate configuration and local overlay references",
                                   "Validate clone, attach, worktrees, guards, services and agent instructions",
                                   "Switch entry points after review; retire duplicates only after parity"],
            "rollback": "Keep original Hub checkout/configuration and restore its entry points; do not move or delete existing work"}


def promote(config, problem, requirement, ownership="unknown", authorized=False):
    # Deliberately accept prose, not file paths, patches or private code.
    if not problem.strip() or not requirement.strip():
        raise HubError("A general problem and public requirement are required")
    state = "ready for human review" if authorized and ownership == "approved-for-public" else "blocked pending ownership and disclosure authorization"
    return {"status": state, "created_at": now(), "problem": problem, "public_requirement": requirement,
            "ownership": ownership, "disclosure_authorized": authorized,
            "copied_material": False, "publication": "requires separate explicit approval",
            "next_steps": ["Confirm the problem itself may be disclosed", "Separate reusable behavior from local policy",
                           "Review ownership and permitted inputs", "Independently implement only within granted rights",
                           "Test with public fixtures", "Prepare Core change; obtain approval before publication"]}
