# Agent Hub Core

This repository contains reusable public infrastructure. Keep personal and
organizational configuration, context, credentials, and experiment results out of
this repository. Do not inspect private implementations without authorization.

Use Python 3.11+ and the standard library. Run `python3.13 -m unittest discover -s
tests -v` and `python3.13 bin/hub secrets` before proposing a release. Use portable
Python executable names on other machines.

Preserve Core / Instance / Personal Overlay ownership. Instances depend on pinned
Core checkouts; do not copy implementation scripts into Instances. Keep provider
adapters narrow. Never imply a configured integration is authenticated.

Strategic conversation does not imply execution. Workers need a bounded intent,
explicit repositories, verification criteria, and isolated worktrees. Durable work
records outlive sessions. Read repository instructions before changing its files.

Never force worktree removal, discard changes, delete branches with extra commits,
or publish Instance-derived material automatically. Promotion requires ownership
and disclosure review; independent reimplementation is not permission to disclose.

