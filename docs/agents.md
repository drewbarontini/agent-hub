# Agent operation and provider boundaries

The shared rules are in Core's `prompts/orchestrator.md` and generated Worker
instructions. Instance `AGENTS.md` points at `.hub/ORCHESTRATOR.md` and optional
`instructions.md`; `CLAUDE.md` imports `AGENTS.md`. Repository-specific instructions
still need to be read: sibling repository instructions are not automatically
inherited just because their path is registered.

## Doctor diagnostics

`doctor` keeps `ready` as the baseline prerequisite check: Python, Git, the selected
runtime executable, registered repositories and the pinned Core checkout. An
installed executable does not demonstrate authentication or successful Worker
execution. Diagnostics do not launch a provider or run a sandbox probe.

The JSON `agent_execution` object reports the selected `runtime` and
`launch_adapter_implemented` (true for Codex, false for Claude). Its
`last_sandbox_probe` object labels the saved probe's runtime as Codex and reports
`status` from `.hub/last-sandbox-probe.json`:

- `not-probed`: no saved report exists.
- `passed`: the saved report records successful local filesystem checks.
- `blocked`: the saved report records a failed probe with a nonzero exit code.
- `unknown`: the report is unreadable, malformed, incomplete or inconsistent.

Probe status does not change `ready`. A saved probe is historical local filesystem
evidence; it does not verify the current environment, Claude permissions, provider
authentication or a completed Worker session. `worker_execution` therefore remains
`unverified`. A passed probe is a precondition for the Codex launch adapter, not a
claim that a Worker ran successfully.

## Codex

v0.1's CLI adapter uses named permission profiles and the `codex sandbox` probe.
It targets current Codex versions supporting `default_permissions`, named
filesystem policies, and `sandbox --permission-profile`. Earlier CLI versions may
reject these flags; update deliberately rather than disabling safeguards. The
development binary was `0.146.0-alpha.9.2`; host enforcement could not be verified
inside the already sandboxed development session.

The preflight refuses loaded user/project configuration containing top-level legacy
`sandbox_mode` or `sandbox_workspace_write`, which can override named permission
selection. It parses provider configuration for this check, never authentication
files, and does not display or rewrite its values. Reconcile conflicting native
configuration deliberately. Organization-managed policy can impose additional
restrictions; no Worker launch is guaranteed by the presence of an executable.

`agent orchestrator` prints a read-only launch plan. `--launch` runs it in the
current terminal. The Orchestrator remains conversational; no work is created
automatically. An operator runs authorized lifecycle commands in another terminal.

`agent worker <id>` prints a plan after checking task worktree identities and
branches. `--launch` first probes the requested local filesystem boundary, then
runs a separate interactive session. Add `--noninteractive` to use `codex exec`
with ignored user config and a ten-minute execution timeout. Hub logs only known
lifecycle event types and exit codes under ignored `.hub/session-logs/`; provider
payloads and stderr are not persisted or echoed by the noninteractive wrapper.
Credentials are resolved by the runtime. Hub never reads authentication files.

Worker policy grants writes only to the work-unit execution directory, protects
each repository's `.git`, `.codex`, `.agents` and `.aws` paths plus shared Git
metadata, disables command network access, and permits no approval escalation.
The probe verifies an inside write, an outside write-open denial, and denial of
write-open access to each worktree's `.git` pointer. It is a useful preflight, not
a proof against every possible escape. See `security.md` for remaining surfaces.

Writes to system temp directories are not granted. Tools needing writable caches
must use paths inside the work unit (for example a local `TMPDIR` set through an
authorized launch environment). Dependencies needing network access must be
prepared by the operator; do not silently broaden Worker policy.

CLI launches add a local session lease to the durable work record. Normal exit
marks it finished; failures mark it interrupted. If the operator process is killed,
the lease may remain running. Check that no process still uses the worktree before
explicitly releasing it. Hub does not infer liveness from stale PIDs.

Workers write `outcome.md` inside their execution directory. `work report` imports
that outcome and records the operator's reviewed summary and verification evidence.
The command labels this evidence as operator-reported, not executed by Hub.

## Claude and mixed configurations

`agent.runtime = "claude"` is recognized, and diagnostics can check CLI presence.
The launch command refuses it explicitly: v0.1 has no tested Claude launch adapter.
Shared `AGENTS.md` rules and a `CLAUDE.md` import provide an instruction compatibility
path, not equivalent permissions, hooks, skills, MCP configuration or sessions.

Before using an existing Claude Hub, validate its native instruction discovery,
permission hooks (including shell writes), sessions, skills and MCP access against
the worktree and cleanup acceptance criteria. Keep its working runtime while
reconciling. Mixed-provider operation is future work; do not substitute Codex
configuration for native Claude configuration.

Sources:

- [Codex permission profiles](https://learn.chatgpt.com/docs/permissions)
- [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference)
- [Claude project instructions and imports](https://code.claude.com/docs/en/memory)
- [Claude hooks](https://code.claude.com/docs/en/hooks)

