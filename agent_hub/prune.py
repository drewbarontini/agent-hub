"""Explicit cleanup of recorded executions, with fresh remote merge evidence."""
from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

from .common import HubError, git, remote_id, run
from .repos import available, executable
from . import setup, work


def ancestor(repo, commit, target):
    # Replacement refs describe local history edits, not the remote's graph.
    return run(["git", "--no-replace-objects", "-C", repo["path"], "merge-base", "--is-ancestor", commit, target],
               check=False).returncode == 0


def branch_head(repo, branch):
    ref = "refs/heads/" + branch
    result = run(["git", "-C", repo["path"], "show-ref", "--verify", "--quiet", ref], check=False)
    if result.returncode == 1:
        return None
    if result.returncode:
        raise HubError("Cannot inspect task branch")
    return git(repo["path"], "rev-parse", "--verify", ref + "^{commit}")


def live_default(repo):
    ref = "refs/heads/" + repo["default_branch"]
    result = run(["git", "-C", repo["path"], "ls-remote", "--exit-code", "origin", ref], check=False)
    lines = result.stdout.splitlines()
    fields = lines[0].split() if len(lines) == 1 else []
    if result.returncode or len(fields) != 2 or fields[1] != ref or not re.fullmatch(r"[0-9a-f]{40}", fields[0]):
        raise HubError("Cannot verify the live origin default branch; work is retained")
    tracked = git(repo["path"], "rev-parse", "--verify", "refs/remotes/origin/" + repo["default_branch"], check=False)
    if tracked != fields[0]:
        raise HubError("Origin tracking ref is missing or stale; fetch explicitly and reassess")
    return fields[0]


def branch_worktrees(repo, branch):
    records, current = [], {}
    for field in git(repo["path"], "worktree", "list", "--porcelain", "-z").split("\0"):
        if field.startswith("worktree "):
            current = {"path": Path(field[9:]).resolve(), "locked": False}
            records.append(current)
        elif field.startswith("branch "):
            current["branch"] = field[7:]
        elif field == "locked" or field.startswith("locked "):
            current["locked"] = True
    return [r for r in records if r.get("branch") == "refs/heads/" + branch]


def github_merge(config, repo, branch, head, default):
    identity = remote_id(repo["remote"]).split("/")
    if len(identity) != 3 or identity[0].lower() != "github.com" or any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in identity[1:]):
        raise HubError("GitHub evidence requires a registered github.com origin")
    binary = executable(config, "gh")
    if not binary:
        raise HubError("GitHub CLI is unavailable; install/authenticate it separately or omit --github")
    owner, name = identity[1:]
    full_name = owner + "/" + name
    result = run([binary, "api", "--hostname", "github.com", "--method", "GET", "--paginate", "--slurp",
                  f"repos/{full_name}/pulls", "-f", f"head={owner}:{branch}",
                  "-f", "state=all", "-f", "per_page=100"], cwd=repo["path"], check=False)
    if result.returncode:
        raise HubError("GitHub lookup failed; work is retained without a fallback")
    try:
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError
        prs = []
        for page in pages:
            for pr in page:
                if (pr["head"]["ref"] != branch or
                        pr["head"]["repo"]["full_name"].lower() != full_name.lower() or
                        pr["base"]["repo"]["full_name"].lower() != full_name.lower()):
                    raise ValueError
                if type(pr["number"]) is not int or pr["state"] not in {"open", "closed"}:
                    raise ValueError
                prs.append(pr)
        if not prs:
            raise HubError("No matching GitHub PR; work is retained")
        if any(pr["state"] == "open" for pr in prs):
            raise HubError("An open GitHub PR still uses this branch")
        pr = max(prs, key=lambda item: item["number"])
        if not pr.get("merged_at"):
            raise HubError("Latest GitHub PR closed without merging")
        if pr["base"]["ref"] != repo["default_branch"]:
            raise HubError("GitHub PR merged into a different base branch")
        pr_head, merged = pr["head"]["sha"], pr["merge_commit_sha"]
        if not all(isinstance(oid, str) and re.fullmatch(r"[0-9a-f]{40}", oid) for oid in (pr_head, merged)):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HubError("Invalid or incomplete GitHub evidence; work is retained") from exc
    if not ancestor(repo, head, pr_head):
        raise HubError("Local branch has commits not proven included in the PR's final head")
    if not ancestor(repo, merged, "refs/heads/" + repo["default_branch"]) or not ancestor(repo, merged, default):
        raise HubError("PR merge commit is not proven present in local and live default branches")
    return pr["number"]


def clean_tree(config, unit, name, expected_head):
    path = work.validate_tree(config, unit, name)
    if git(path, "rev-parse", "HEAD") != expected_head:
        raise HubError("Task branch changed during cleanup assessment")
    work.check_index_flags(path)
    if git(path, "--no-optional-locks", "--no-replace-objects", "status", "--porcelain", "--untracked-files=all", "--ignored=matching"):
        raise HubError("Worktree has changed, untracked or ignored files" + setup.cleanup_notice(unit, name))


def require_local_history(repo):
    # Partial clones can fetch objects while otherwise read-only Git commands
    # inspect history or files. Reject them before running status or ancestry.
    result = run(["git", "-C", repo["path"], "config", "--get-regexp",
                  r"^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter))$"], check=False)
    if result.returncode not in {0, 1}:
        raise HubError("Cannot verify local object availability; work is retained")
    for line in result.stdout.splitlines():
        key = line.split(maxsplit=1)[0]
        if not key.endswith(".promisor") or git(repo["path"], "config", "--type=bool", "--get", key) == "true":
            raise HubError("Partial clone retained to avoid implicit object fetching; complete local history is required")


def repository_plan(config, unit, name, delete_branches, github):
    repo, entry = config.repo(name), unit["repos"][name]
    require_local_history(repo)
    available(repo)
    branch = entry["branch"]
    if branch == repo["default_branch"]:
        raise HubError("Default branches are never cleanup candidates")
    path = work.location(config, unit["id"], name)
    head = branch_head(repo, branch)
    plan = {"name": name, "branch": branch, "head": head, "remove_worktree": path.exists(),
            "delete_branch": False, "branch_reason": "Branch retention is the default"}
    if head is None:
        if path.exists():
            raise HubError("Recorded branch is missing but its worktree remains")
        plan["branch_reason"] = "Branch and worktree are already absent"
        return plan
    checked_out = branch_worktrees(repo, branch)
    if any(r["path"] != path.resolve() for r in checked_out):
        raise HubError("Task branch is checked out outside its recorded worktree")
    if any(r["locked"] for r in checked_out):
        raise HubError("Task worktree is locked; inspect it manually")
    if checked_out and not path.exists():
        raise HubError("Worktree registration remains but its directory is missing; recover it manually")
    if path.exists():
        clean_tree(config, unit, name, head)
    if not ancestor(repo, entry["base"], head):
        raise HubError("Task branch no longer contains its recorded base; inspect its history")
    default = live_default(repo)
    merged = ancestor(repo, head, "refs/heads/" + repo["default_branch"]) and ancestor(repo, head, default)
    if github:
        plan["pull_request"] = github_merge(config, repo, branch, head, default)
    if not merged and not github:
        raise HubError("Task commits are not merged in local and live default; --github can assess squash merges")
    plan.update(default_oid=default, merge="ancestry" if merged else "pr-evidence")
    if delete_branches:
        # A PR can prove that a squash result landed without preserving the
        # original commit objects on default. Keep that branch as recovery.
        plan["delete_branch"] = merged
        plan["branch_reason"] = "Commits are present in local and live default" if merged else (
            "PR merge is verified, but original commits are not on default; branch retained")
    return plan


def unit_plan(config, identifier, delete_branches, github):
    unit = work.load(config, identifier)
    row = {"id": identifier, "key": (unit.get("source") or {}).get("key"),
           "title": unit["title"], "state": "kept", "repos": [], "reasons": []}
    if any(s["status"] in {"running", "interrupted"} for s in unit["sessions"]):
        row["reasons"].append("Running or interrupted session; verify it ended and release it explicitly")
    elif unit["status"] not in {"review", "cleaned"}:
        row["reasons"].append("Work has not reached review; cleanup does not infer completion")
    elif not unit["repos"]:
        row["reasons"].append("No repository worktrees; execution artifacts are retained")
    else:
        for name in unit["repos"]:
            try:
                row["repos"].append(repository_plan(config, unit, name, delete_branches, github))
            except HubError as exc:
                row["repos"].append({"name": name, "problem": str(exc)})
                row["reasons"].append(f"{name}: {exc}")
        if not row["reasons"]:
            if any(p["remove_worktree"] or p["delete_branch"] for p in row["repos"]):
                row["state"] = "eligible"
            else:
                row["reasons"].append("No removable worktrees or eligible branch deletions; metadata is retained")
    return unit, row


def apply_unit(config, unit, row):
    row.update(removed_worktrees=[], deleted_branches=[])
    for plan in row["repos"]:
        name, branch, head = plan["name"], plan["branch"], plan["head"]
        repo = config.repo(name)
        if head is None:
            continue
        if branch_head(repo, branch) != head:
            raise HubError("Task branch changed before removal; reassess")
        if plan["remove_worktree"]:
            clean_tree(config, unit, name, head)
            run(["git", "-C", repo["path"], "worktree", "remove", work.location(config, unit["id"], name)])
            row["removed_worktrees"].append(name)
        if plan["delete_branch"]:
            if branch_head(repo, branch) != head:
                raise HubError("Task branch changed before deletion; branch retained")
            # Git retains its own checked-out/merged-branch safeguards; never -D.
            run(["git", "-C", repo["path"], "branch", "--delete", "--", branch])
            row["deleted_branches"].append(name)
    unit["status"] = "cleaned"
    work.persist(config, unit)
    row["state"] = "cleaned"


def prune(config, identifier=None, *, apply=False, delete_branches=False, github=False):
    if identifier is not None and not work.record_path(config, identifier).exists():
        raise HubError("Unknown execution ID; inspect hub status for recorded executions")
    identifiers = [identifier] if identifier is not None else sorted(p.parent.name for p in (config.root / "work").glob("*/unit.json"))
    rows, failed = [], False
    with work.mutation(config) if apply else contextlib.nullcontext():
        for identifier in identifiers:
            try:
                unit, row = unit_plan(config, identifier, delete_branches, github)
                if apply and row["state"] == "eligible":
                    # Re-read all source, file, lease and remote evidence before
                    # acting; a dry-run result is never a reusable deletion permit.
                    current_unit, current = unit_plan(config, identifier, delete_branches, github)
                    if current != row or current_unit != unit:
                        row["state"] = "kept"
                        row["reasons"].append("Cleanup evidence changed during assessment; reassess")
                    else:
                        try:
                            apply_unit(config, unit, row)
                        except (HubError, OSError) as exc:
                            row["state"] = "failed"
                            row["reasons"].append(str(exc) if isinstance(exc, HubError) else
                                                  "Cannot persist cleanup state; inspect the reported removals before retrying")
                            failed = True
                rows.append(row)
            except (HubError, KeyError, TypeError, ValueError, AttributeError) as exc:
                reason = str(exc) if isinstance(exc, HubError) else "Invalid execution metadata; inspect it manually"
                rows.append({"id": identifier, "state": "kept", "reasons": [reason], "repos": []})
    return {"applied": apply, "delete_branches": delete_branches, "github": github,
            "work": rows, "exit_code": 1 if failed else 0,
            "metadata_and_artifacts": "retained", "automatic_cleanup": "disabled"}
