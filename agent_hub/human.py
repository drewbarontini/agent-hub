"""Compact, read-only presentation of observed Hub execution state."""
from __future__ import annotations

import json


def text(value):
    return "".join(f"\\u{ord(c):04x}" if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in str(value))


def next_action(row):
    identifier = row["id"]
    if row.get("problem"):
        return "Inspect and repair the execution record before continuing."
    sessions = row.get("sessions", [])
    if any(s["status"] == "running" for s in sessions):
        return "Inspect the running session; wait for it to finish before changing lifecycle state."
    if any(s["status"] == "interrupted" for s in sessions):
        return f"Verify interrupted processes have ended, then use hub work release {identifier} --help."
    repos = row["repos"].values()
    if any(r.get("problem") for r in repos):
        return "Inspect and repair the worktree problem before continuing."
    state = row["status"]
    if state == "cleaned":
        if any(r["present"] for r in repos):
            return "Inspect remaining worktrees."
        return "No action; execution history is retained."
    if state == "planned":
        return f"hub work start {identifier}"
    if any(not r["present"] for r in repos):
        return "Inspect missing worktrees before resuming or cleaning up."
    if any(r.get("setup", {}).get("state") in {"running", "interrupted"} for r in repos):
        return "Verify prior setup processes have ended and inspect the receipt before retrying."
    if state == "prepared" and any(r.get("setup", {}).get("state") in {
            "not-run", "failed", "configuration-changed", "invalid-receipt"} for r in repos):
        return f"Inspect setup state; preview hub work setup {identifier}."
    if any(r.get("checks", {}).get("state") in {"failed", "unconfigured", "interrupted", "invalid-receipt"} for r in repos):
        return "Inspect the last check receipt and resolve verification failures before reporting completion."
    if state == "review":
        return f"Review outcome and verification; after merge, preview hub work prune {identifier}."
    if state == "prepared":
        if not row["repos"]:
            return "Complete the bounded analysis and record the outcome on its source."
        if any(r.get("dirty") for r in repos):
            return "Review changed files and run the repository's required checks."
        return f"hub agent worker {identifier} (launch plan only)"
    return "Inspect the recorded state before continuing."


def status(result):
    lines = []
    if isinstance(result, dict):
        lines.append(f"Repositories ({len(result['repositories'])})")
        for repo in result["repositories"]:
            detail = repo.get("problem") or (f"{repo['branch']} | " + ("changed" if repo["dirty"] else "clean"))
            lines.append(f"  {text(repo['name'])}: {text(detail)}")
        rows = result["work"]
        lines.append("")
    else:
        rows = result
    lines.append(f"Work ({len(rows)}) — local execution state")
    if not rows:
        lines.append("  No recorded work. Resolve a source ticket before starting work.")
    for row in rows:
        label = f"{row['key']} / {row['id']}" if row.get("key") else row["id"]
        lines += ["", f"{text(label)} [{text(row.get('status', 'unavailable'))}] {text(row.get('title', ''))}".rstrip()]
        if row.get("problem"):
            lines.append(f"  Problem: {text(row['problem'])}")
        sessions = row.get("sessions", [])
        visible = [s for s in sessions if s["status"] in {"running", "interrupted"}]
        if sessions and sessions[-1] not in visible:
            visible.append(sessions[-1])
        if not visible:
            lines.append("  Session: none recorded")
        for session in visible:
            exit_code = f" (exit {session['exit_code']})" if session.get("exit_code") is not None else ""
            lines.append(f"  Session {text(session.get('id', '?'))}: {text(session['status'])}{text(exit_code)}")
        for name, repo in row.get("repos", {}).items():
            if repo.get("problem"):
                state = repo["problem"]
            elif not repo["present"]:
                state = "missing"
            else:
                state = "changed" if repo["dirty"] else "clean"
            commits = f" | {repo['commits_since_base']} commits since base" if "commits_since_base" in repo else ""
            lines.append(f"  {text(name)}: {text(repo['branch'])} | {text(state)}{text(commits)}")
            if "setup" in repo:
                setup_state = text(repo["setup"]["state"])
                qualifier = " (last run; application checks not run)" if repo["setup"].get("ready") is True else " (readiness unverified)"
                lines.append(f"    Setup: {setup_state}{qualifier}")
            if "checks" in repo:
                lines.append(f"    Checks: {text(repo['checks']['state'])} (last recorded result)")
            files = repo.get("changed_files", [])
            for item in files[:8]:
                path = json.dumps(item["path"], ensure_ascii=True)
                if "original_path" in item:
                    path = json.dumps(item["original_path"], ensure_ascii=True) + " -> " + path
                lines.append(f"    {text(item['status'])} {path}")
            if len(files) > 8:
                lines.append(f"    + {len(files) - 8} more changed files; inspect Git status")
        lines.append("  Next: " + text(next_action(row)))
    return "\n".join(lines)
