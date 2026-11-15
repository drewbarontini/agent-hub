# Context navigation and capability inventory

Agent Hub provides a **home for coordination**, not a new storage system. An Instance
references authoritative work, learning, documentation, repositories, and capabilities.
The Orchestrator should navigate only the context relevant to the current intention.

Examples use the Instance's local `hub` launcher after the optional
[session PATH setup](getting-started.md#use-the-instance-cli). They do not
require a global installation.

## Index: Board, Memory, Docs, and capabilities

The Workspace command generates an ignored local index at `.hub/CONTEXT.md`.
It is derived from `hub.toml` and `repos.toml` and therefore cannot become an
independently maintained registry.

```sh
hub context --write
hub context
hub context --section resources
hub context --section repositories
```

The root index shows a bounded number of entries, summary availability, and links
to local detail pages if the registry grows. Resource details show their declared
purpose and use instructions. A configured resource is **not** proof that a native
provider is installed, authenticated, reachable, or authorized for a specific
task. The index never reads remote boards or knowledge documents, installs
skills, clones repositories, or materializes sources.

**Board** is an external authoritative work source, not a new Hub task registry.
**Memory / Docs** means existing decision, learning, project and architectural
references; neither is a mandatory new database. **Capabilities** includes
registered skills, tools and MCP references, which remain independently owned.

The index is ignored under `.hub/`, contains only registry-derived references,
and is regenerated on `hub workspace` or explicitly with `hub context --write`.
For stale information, regenerate it rather than editing its output. Workers
receive only delegated, authorized references from their work units; the full
index must not be copied into every Worker prompt.

## Inventory: conservative shared-material review

```sh
hub inventory                    # Known files in every registered available repo
hub inventory --repo frontend    # A registered subset
hub inventory --repo frontend --repo backend
```

Only explicitly registered, identity-verified repositories are considered.
The command checks fixed, shallow paths for `AGENTS.md`, `CLAUDE.md`,
`.agents/skills/*/SKILL.md`, and `.claude/skills/*/SKILL.md`.
It skips symlinks and oversized candidates and avoids recursive home, project,
document and secret scans. Repository identity must match the registered origin
and default-branch requirements.

The output includes repository-relative paths, exact-byte duplicate matches,
and same-name overlap flags. No file body or content hash is emitted.
Exact duplicates are **not** evidence of shared ownership or a reason to move
files; same-name overlap is only a cue for human inspection, not semantic
equivalence. A missing candidate is not proof that the repo lacks a capability.

Review findings through the existing **Adopt / Preserve / Promote candidate /
Retire** framework. Never copy organization-specific material into public Core,
relocate instructions, install missing tools, or promote a pattern without
appropriate ownership and disclosure authorization.

## Working practice

1. The human and Orchestrator examine the configured Board.
2. The Orchestrator follows only relevant Memory, Docs, repositories and skills.
3. They agree on the outcome and what to delegate.
4. A Worker executes with bounded, verified source access.
5. Results and decisions return to the owning work artifact; the index stays a map.

This adapts ideas from [The Home Repo Pattern](https://www.aihero.dev/the-home-repo-pattern)
while preserving the Agent Hub operating model: **Orchestrator · Workers · Context**.
