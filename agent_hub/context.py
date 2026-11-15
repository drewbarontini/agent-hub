"""Instance context navigation and bounded, read-only capability inventory."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .common import HubError, write
from .repos import inspect, resources

LIMIT = 6
PAGE_SIZE = 20
MAX_SIZE = 256_000


def label(value):
    """Make registry values inert, single-line Markdown."""
    return re.sub(r"[\r\n\t\[\]<>|]", " ", str(value or "")).strip().replace(chr(96), "'")


def safe_reference(value):
    """Do not reproduce URL credentials, query tokens or fragments in a generated map."""
    text = str(value or "")
    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https"}:
        if parsed.username or parsed.password:
            return "[URL credentials omitted]"
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if "://" in text or len(text) > 240:
        return "[unverified reference]"
    return label(text)


def catalog(config, section="summary"):
    if section not in {"summary", "repositories", "resources"}:
        raise HubError("Unknown context section")
    repositories = []
    for entry in config.repos.values():
        diag = inspect(entry)
        repositories.append({
            "name": entry["name"], "description": entry.get("description", ""),
            "available": diag["available"], "visible": entry["visible"],
            "problem": diag["problem"],
        })
    diagnostics = {d["name"]: d for d in resources(config)}
    refs = [
        {"name": item["name"], "kind": item["kind"],
         "purpose": item.get("purpose", ""), "usage": item.get("usage", ""),
         "reference": safe_reference(config.path(item["path"]) if "path" in item
                                     else item.get("location", "")),
         "availability": diagnostics[item["name"]]["availability"],
         "connectivity": diagnostics[item["name"]]["connectivity"]}
        for item in config.resources
    ]
    if section == "repositories":
        return {"section": section, "repositories": repositories}
    if section == "resources":
        return {"section": section, "resources": refs}
    return {"section": section, "instance": config.data["instance"]["name"],
            "board": [x for x in refs if x["kind"] == "work"],
            "knowledge": [x for x in refs if x["kind"] == "context"],
            "capabilities": [x for x in refs if x["kind"] not in {"work", "context"}],
            "repository_count": len(repositories),
            "available_repository_count": sum(x["available"] for x in repositories),
            "note": "References only; presence never proves provider connectivity or authorization."}


def resource_line(item):
    return ("- **" + label(item["name"]) + "** — " + (label(item["purpose"]) or "No purpose") +
            "; " + label(item["availability"]) + "; connection: " + label(item["connectivity"]) +
            ("; source: " + label(item["reference"]) if item["reference"] else ""))


def repo_line(item):
    state = "available" if item["available"] else "unavailable"
    if not item["available"] and item["problem"]:
        state += ": " + label(item["problem"])
    purpose = label(item["description"])
    return "- **" + label(item["name"]) + "** — " + (purpose + "; " if purpose else "") + state


def render(config):
    """Generated local Markdown, progressively linking to more details."""
    summary = catalog(config)
    repos = catalog(config, "repositories")["repositories"]
    refs = catalog(config, "resources")["resources"]
    files = {}
    lines = ["# Agent Hub — Context Index", "",
             "Generated from Instance configuration. Not an authoritative registry.",
             "Read only relevant references; no source is copied, authenticated or synchronized.", ""]
    groups = [
        ("Board", summary["board"], "Canonical work sources; not a mirrored ticket list."),
        ("Knowledge (Memory / Docs)", summary["knowledge"], "Context references, not a new knowledge database."),
        ("Capabilities and tools", summary["capabilities"], "Skills and tools may require native installation or authorization."),
    ]
    for title, rows, note in groups:
        lines += ["## " + title, "", note, ""]
        lines += [resource_line(x) for x in rows[:LIMIT]] or ["- None registered"]
        if len(rows) > LIMIT:
            lines.append("- " + str(len(rows) - LIMIT) + " more: [All resources](context/resources.md)")
        lines.append("")
    lines += ["## Repositories", "",
              str(summary["available_repository_count"]) + " of " +
              str(summary["repository_count"]) + " registered repositories available.", ""]
    lines += [repo_line(x) for x in repos[:LIMIT]] or ["- None registered"]
    if len(repos) > LIMIT:
        lines.append("- " + str(len(repos) - LIMIT) + " more: [All repositories](context/repositories.md)")
    lines += ["", "## Navigation", "",
              "1. Review the configured Board with the human before delegating.",
              "2. Follow only relevant knowledge, docs and repository references.",
              "3. Verify external connectivity and read repo-specific instructions before work.",
              "4. Delegate bounded execution, keeping outcomes in the owning work artifact.", "",
              "Use the context command with --section resources or --section repositories for details.", ""]
    files["CONTEXT.md"] = "\n".join(lines)
    details = ["# Registered resources", "", "References only; connectivity is not inferred.", ""]
    for x in refs:
        details += ["## " + label(x["name"]), "", "- Kind: " + label(x["kind"]),
                    "- Purpose: " + label(x["purpose"]),
                    "- Availability: " + label(x["availability"]),
                    "- Connectivity: " + label(x["connectivity"])]
        if x["reference"]:
            details.append("- Source: " + label(x["reference"]))
        if x["usage"]:
            details.append("- Usage: " + label(x["usage"]))
        details.append("")
    files["context/resources.md"] = "\n".join(details) + "\n"
    repo_index = ["# Registered repositories", "", "Repositories retain independent ownership.", ""]
    for i in range(0, len(repos), PAGE_SIZE):
        subset = repos[i:i + PAGE_SIZE]
        if len(repos) > PAGE_SIZE:
            page = i // PAGE_SIZE + 1
            files["context/repositories-" + str(page) + ".md"] = (
                "# Repositories page " + str(page) + "\n\n" +
                "\n".join(repo_line(row) for row in subset) + "\n")
            repo_index.append("- [Page " + str(page) + "](repositories-" + str(page) +
                              ".md): " + str(len(subset)) + " repositories")
        else:
            repo_index.extend(repo_line(row) for row in subset)
    files["context/repositories.md"] = "\n".join(repo_index) + "\n"
    return files


def write_index(config):
    files = render(config)
    for relative, body in files.items():
        write(config.root / ".hub" / relative, body)
    return {"index": str(config.root / ".hub/CONTEXT.md"), "generated_files": len(files)}


def candidate_files(root):
    """No recursive home/docs scan, no symlinks or provider settings."""
    paths = [root / "AGENTS.md", root / "CLAUDE.md"]
    for name in (".agents/skills", ".claude/skills"):
        directory = root / name
        if directory.is_dir() and not directory.is_symlink():
            paths += sorted(directory.glob("*/SKILL.md"))
    return paths


def inventory(config, selected=None):
    """Only registered, identity-verified repos. Report paths, never file bodies."""
    selected = list(dict.fromkeys(selected if selected is not None else config.repos.keys()))
    for name in selected:
        config.repo(name)
    items, skipped = [], []
    for name in selected:
        repo = config.repo(name)
        if not inspect(repo)["available"]:
            skipped.append({"repository": name, "reason": "unavailable"})
            continue
        for path in candidate_files(repo["path"]):
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SIZE:
                    continue
                # Parent symlinks must not escape the registered repo.
                if not path.resolve().is_relative_to(repo["path"].resolve()):
                    continue
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                items.append({"repository": name, "path": path.relative_to(repo["path"]).as_posix(), "_sha": sha})
            except (OSError, ValueError):
                skipped.append({"repository": name, "reason": "one candidate unreadable"})
    hashes, names = defaultdict(list), defaultdict(list)
    for item in items:
        hashes[item["_sha"]].append(item)
        names[Path(item["path"]).name].append(item)
    for item in items:
        peers = [x for x in hashes[item["_sha"]] if x is not item]
        item["classification"] = ("exact duplicate" if peers else
                                   "name overlap (review only)" if len(names[Path(item["path"]).name]) > 1
                                   else "unique / scope unverified")
        item["matches"] = [x["repository"] + ":" + x["path"] for x in peers]
    return {"scope": selected,
            "items": [{key: value for key, value in x.items() if key != "_sha"} for x in items],
            "unavailable_or_unreadable": skipped,
            "limits": ("Read-only known agent files in registered repos. No contents exposed, "
                       "no semantic classification, no migration or public promotion.")}
