# Getting started

## Discover and propose

Start in a committed Core checkout. Use Python 3.11+; `python3.13` below is an
example executable, not a required minor version. Discovery only scans explicit
roots, at a bounded depth, and stops at repository boundaries:

```sh
python3.13 bin/hub discover --root /approved/projects --depth 2
```

The report lists Git metadata, instruction filenames, native skill directories,
and whether a project `.mcp.json` exists. It does not read context documents,
credentials, skills, or MCP configuration contents. It does not infer remote
authentication. Discover user-level MCPs and skills through provider-native tools
only after authorization. See `prompts/initialize.md` for the conversational flow.

Review repository selection, remotes, branches, clone/attach choices, visibility,
work sources, context locations, skills, services and local overrides. Unknown
connections remain unverified. Configuration changes happen after proposal review.

## Configure

```sh
python3.13 bin/hub init /approved/my-hub --name my-hub --core-source . --ref HEAD
```

Initialization refuses a nonempty destination unless it already contains a valid
Instance. Repeating initialization preserves its configuration and reinstalls a
missing pinned Core. If interrupted during first initialization, inspect the
partial directory and use a new empty destination; do not blindly erase it.

### Use the Instance CLI

The initializer creates an executable `.hub/bin/hub` launcher pointing to the
Instance's **pinned Core**, not your editable Core checkout. From the initialized
Instance root, expose it for **this shell session only** when using an external terminal:

```sh
cd /approved/my-hub
export PATH="$PWD/.hub/bin:$PATH"
hub config-check
```

You can now use `hub bootstrap`, `hub workspace`, `hub doctor`,
`hub context`, and other normal commands in that terminal. Repeat the
`export` in each new external shell; it does not edit shell profiles, install a global
command, or change `core.lock`. If you switch Instances, switch to the target
Instance and update PATH for that session. Run commands from the Instance root
(or pass `--instance /approved/my-hub` before the command).

Generated VS Code workspaces configure new macOS/Linux terminals automatically:
PATH starts with the Instance's `.hub/bin`, and `HUB_INSTANCE` selects that
Instance even when the terminal opens in a repository folder. Open or reload the
generated workspace and create a new terminal to receive these settings. Explicit
`--instance` overrides `HUB_INSTANCE`; outside the workspace, an unset variable
keeps the current-directory default. When switching Instances inside a workspace
terminal, use the target Instance's launcher and explicit `--instance`, or open
its generated workspace. Shell profiles and global installation are unchanged.

Use `hub status --human` for compact repository/work status and suggested next
actions, or run the generated **Hub: status** task. Both `hub status` and
`hub work status <id-or-key>` retain JSON by default; `--json` selects it explicitly.

The launcher starts via `#!/usr/bin/env python3`, so `python3` on PATH must
be **3.11 or newer**. Without the PATH step, run `./.hub/bin/hub doctor` when
that Python requirement is met. If `python3` is older or unavailable, use the
explicit interpreter instead: `python3.13 .hub/bin/hub doctor` (or any
installed Python 3.11+ executable). No package manager or new wrapper is needed.

Edit `repos.toml`. Replace the empty `repos = []` with entries adapted from
`templates/instance/repos.toml`. Use the actual origin and actual default branch.
Names and folders need not match the remote's repository name. `checkout = true`
permits bootstrap cloning; `false` registers a resource without cloning it.

Use `local.toml` for existing repositories outside the default sibling location:

```toml
[repos.example]
path = "/approved/existing/project"

[tools]
codex = "/path/to/codex"
```

Register resources in `hub.toml`; use an approved external overlay when individual
references should stay outside shared configuration. Do not store credentials in
any of these files. Repositories can stay hidden from the Explorer with
`visible = false` while remaining available to agents.

## Verify and open

From the Instance directory, after the session PATH step above:

```sh
hub config-check
hub bootstrap
hub resources
hub doctor
hub workspace
code .hub/hub.code-workspace
```

Doctor's exit status is nonzero when required prerequisites or registered
repositories are unavailable. Optional resources produce explicit availability and
connectivity information. A passing doctor is not a passing runtime sandbox test.

Launch the Orchestrator using the workspace task or CLI command. Agent launch
plans use explicit permissions and `never` approval escalation. The CLI
Orchestrator cannot mutate Hub state in read-only mode: run authorized lifecycle
commands in another terminal. Native IDE agents have independent permission
settings; a generated workspace cannot enforce those settings.

Create a small work unit, prepare it, run `sandbox-check`, and launch a Worker as
shown in README.md. If the host cannot enforce the requested sandbox, stop there
and diagnose the host/runtime. Do not disable sandboxing to make the demo pass.

## Navigate without duplicating Context

After generating the workspace, open `.hub/CONTEXT.md` for a concise map of the
Instance's configured Board, Memory/Docs, repositories, and tools. The generated
index is ignored and may be regenerated after changing `hub.toml` or
`repos.toml`:

```sh
hub context --write
hub context --section resources
hub context --section repositories
```

For a read-only scan of registered instructions and skills:

```sh
hub inventory --repo example
```

Only explicitly registered repositories are considered. No home-directory scan,
file migration, provider login, or remote syncing is performed.

## Another machine

Commit the Instance's intended configuration and Core lock to its independently
owned repository. Keep execution metadata ignored and use the canonical work
source for requirements, outcomes and verification. After cloning it elsewhere,
run initialization from an available Core checkout against that existing Instance.
Provide local overrides for repository paths, executable paths and overlays;
bootstrap the repositories and regenerate the workspace. The pinned Core commit
must be reachable from its source. Before public release, provide an explicit
local Core source in `local.toml` on each machine.

Native sessions, caches, credentials, uncommitted changes and local worktrees are
not transferred. Push authorized task branches through their repository's normal
review process. Work records identify branches and base commits for manual recovery
or another prepared session; v0.1 refuses automatic ambiguous branch reattachment.

