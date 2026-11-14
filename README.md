# Agent Hub

**One core. Many contexts. Independent ownership.**

Agent Hub coordinates repositories, AI agents, context references, tools, and work
without taking ownership of those resources. Core defines how; an Instance defines
what; the local environment resolves where.

v0.1 is a Python standard-library CLI with TOML configuration, Git worktree
isolation, durable work handoffs, a generated VS Code workspace, and deliberate
Core updates. There is no server, database, custom editor extension, or mandatory
work-management provider.

## Start

Requirements: Python **3.11+**, Git **2.31+**, and macOS or Linux. VS Code and Codex
are needed for the agent workspace experience. On machines whose `python3` is
older, use an explicit executable such as `python3.13` in these commands.

```sh
git clone https://github.com/drewbarontini/agent-hub.git
cd agent-hub
python3.13 bin/hub --help
python3.13 -m unittest discover -s tests -v
```

Copy this into your coding agent:

> Read `prompts/initialize.md` and `docs/getting-started.md` in this Core checkout.
> Help me initialize an independent Hub Instance using Discover → Propose →
> Configure → Verify. Ask which project roots I authorize for discovery and where
> the Instance should live. Present the configuration proposal before applying it.
> Keep local paths, private context, and credentials out of public Core. Register
> Core itself as an editable resource separate from the pinned runtime. Verify
> what works and explicitly report missing connections or runtime limitations.

For deterministic setup after reviewing your proposal:

```sh
python3.13 bin/hub init ../my-hub --name my-hub --core-source . --ref HEAD
cd ../my-hub
# Configure hub.toml, repos.toml and ignored local.toml first.
python3.13 .hub/bin/hub bootstrap
python3.13 .hub/bin/hub workspace
python3.13 .hub/bin/hub doctor
code .hub/hub.code-workspace
```

The intended public remote may not exist yet during prepublication development.
Initialization also works from any committed local Core checkout. The Instance
gets its own Git repository and a detached, pinned Core installation.

## Work with agents

The **Orchestrator** strategizes, coordinates, and integrates. Exploration can stay
exploration. **Workers** execute bounded work in separate work-unit directories.
The workspace is their environment, not another agent role.

```sh
python3.13 .hub/bin/hub agent orchestrator --launch
# In another terminal, from the Instance:
python3.13 .hub/bin/hub work create --title "Inspect project" \
  --intent "Investigate the configured test command; change no application code" \
  --repo example --verify "Record the command and its actual result"
python3.13 .hub/bin/hub work prepare W-REPLACE_WITH_ID
python3.13 .hub/bin/hub sandbox-check W-REPLACE_WITH_ID
python3.13 .hub/bin/hub agent worker W-REPLACE_WITH_ID --launch
python3.13 .hub/bin/hub work report W-REPLACE_WITH_ID \
  --summary "Reviewed Worker outcome" --verification "Record evidence here"
```

Without `--launch`, agent commands print their launch plans. A Worker launch
requires a passing filesystem sandbox probe; it never falls back to unrestricted
execution. Local session logs contain lifecycle event types and exit codes only.
Execution records and temporary handoffs stay ignored and machine-local; canonical
requirements, outcomes and verification stay in the configured work source.
Create a local execution record only when execution needs it. An agent session is
not a work unit.

## Boundaries and current support

| Boundary | Owns |
| --- | --- |
| Core | Reusable tools, conventions, prompts, templates, tests |
| Instance | Identity, registry, resource references, local policies and ignored execution metadata |
| Personal Overlay | Optional individual references and preferences in an approved location |

| Capability | v0.1 status |
| --- | --- |
| Initialization, attach/clone, visibility, workspace, diagnostics | Implemented and covered by Git integration tests |
| Multi-repository worktrees, cleanup checks, optional branch hooks | Implemented and tested with disposable repositories |
| Codex launch plans, leases and outcome handoffs | Implemented; real launch requires supported Codex permissions and host sandbox |
| Codex filesystem enforcement on this development host | Nested sandbox creation is blocked; native CLI end-to-end execution is unverified here |
| Claude / mixed providers | Instruction compatibility documented; launch adapter not implemented |
| Linear, Notion, GitHub work providers and MCP connectivity | References only; no authenticated connectors implemented |
| Editor layout, conversation synchronization | Manual layout; no cross-machine session synchronization |

See [validation](docs/validation.md) for actual results and limitations.

## Read more

- [Getting started](docs/getting-started.md) and [configuration](docs/configuration.md)
- [Architecture](docs/architecture.md) and [decision record](docs/decisions/001-core-and-instance.md)
- [Workspace](docs/workspace.md), [agents](docs/agents.md), and [operations](docs/operations.md)
- [Adopt, Reconcile, Promote](docs/evolution.md)
- [Security and ownership](docs/security.md), [contributing](CONTRIBUTING.md), and [roadmap](docs/roadmap.md)

MIT licensed. Publication, remote creation, and Instance-derived disclosure always
require explicit authorization from the appropriate owner.

