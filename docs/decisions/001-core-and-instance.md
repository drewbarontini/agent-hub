# ADR 001: a pinned Core checkout and independently owned Instance

Status: accepted, 2026-11-14.

Core is a Python 3.11+ standard-library CLI. An Instance has its own Git history,
`hub.toml`, `repos.toml`, durable `work/` metadata, and optional instructions.
Ignored local settings resolve machine paths and an optional external overlay.

Each Instance installs a detached Core checkout at `.hub/cores/<commit>`. A portable
`core.lock` records the source and full commit. Local source paths belong in
`local.toml`, not portable configuration. No Instance contains copied Core scripts.
Invoke the CLI directly from the active pinned checkout. Updates stage a new
checkout, run tests and configuration checks, and switch the lock only after success.
The previous lock is kept for explicit rollback.

This is simpler to inspect than an application server, submodules, or a package
registry, and works before the public remote exists. Core development uses a
separate registered checkout and task worktrees, leaving the installed Core intact.

The Orchestrator starts in an Instance with read-only defaults. CLI Workers start
in a work-unit directory with workspace-write sandboxing and no approval escalation
by default. Git metadata and ordinary checkouts are outside their writable scope.
An operator performs commits and lifecycle mutations through Hub commands. Native
editor agent panels are optional; their permissions must be configured separately.

TOML config is layered: shared configuration, optional external overlay, then
machine-local overrides. Local repository paths never become shared defaults.
Manual work uses UUIDs; remote work sources remain authoritative. JSON records and
Markdown handoffs store recovery information, not a new project-management system.

Implementation order: configuration and initialization; repositories and diagnostics;
worktrees and sessions; evolution workflows; lifecycle/security validation; personal
self-hosting experiment and documentation. No external publication is authorized.
