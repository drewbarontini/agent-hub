from __future__ import annotations

import re
from pathlib import Path

from .common import HubError, run

# Practical leak detection, not a proof that material is safe to publish.
PATTERNS = [r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", r"\bgithub_pat_[A-Za-z0-9_]{30,}\b",
            r"\bsk-[A-Za-z0-9_-]{32,}\b", r"\bAKIA[A-Z0-9]{16}\b",
            r"https?://[^/\s]+:[^/@\s]+@"]


def scan_text(text):
    return any(re.search(pattern, text) for pattern in PATTERNS)


def scan(root, staged=False):
    root = Path(root).resolve()
    args = ["git", "-C", root]
    if staged:
        paths = run(args + ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]).stdout.split("\0")
    else:
        paths = run(args + ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]).stdout.split("\0")
    findings = []
    for name in paths:
        if not name:
            continue
        parts = Path(name).parts
        if ".hub" in parts or Path(name).name == "local.toml" or (Path(name).name.startswith(".env") and Path(name).name != ".env.example"):
            findings.append({"file": name, "reason": "private/generated file selected by Git"})
            continue
        p = root / name
        if p.is_symlink():
            if not p.resolve().is_relative_to(root):
                findings.append({"file": name, "reason": "symlink outside repository"})
            continue
        if staged:
            content = run(args + ["show", ":" + name]).stdout
        else:
            if not p.is_file():
                continue
            if p.stat().st_size > 2_000_000:
                findings.append({"file": name, "reason": "too large for scanner; manual inspection required"})
                continue
            content = p.read_bytes().decode("utf-8", errors="replace")
        if scan_text(content):
            findings.append({"file": name, "reason": "possible credential; value withheld"})
    return {"passed": not findings, "findings": findings,
            "limits": "Heuristic scanning; review ownership, disclosure rights and all staged material before publication"}

