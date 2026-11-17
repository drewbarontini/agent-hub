# Operations

Run commands from an initialized Instance with its local `hub` launcher
on your session PATH (see [Instance CLI](getting-started.md#use-the-instance-cli)).
The launcher still requires Python 3.11+ as `python3`:

```sh
hub status
hub doctor
hub resources
```

In a generated VS Code workspace, new macOS/Linux terminals inherit the pinned
launcher on PATH and `HUB_INSTANCE`, so these commands also work from repository
folders. An explicit `--instance` takes precedence over that workspace default.

```sh
hub status --human
hub work status APP-123 --human
hub status --json
```

JSON remains the default on both status commands. The human view shows source
keys, branches, changed files (up to eight per worktree), session state and next
actions. Filenames preserve raw bytes and control characters through escaped,
quoted display; rename pairs retain both names. Status describes
local execution state, not canonical ticket completion or live process liveness.
Its suggestions run nothing and do not prove that cleanup is safe; inspect
interrupted processes before releasing sessions and preview cleanup after merge.
Missing or invalid work is reported for inspection rather than silently omitted.

## Bounded work

After reading the canonical ticket and agreeing on the execution scope, start
with one command:

```sh
hub work start APP-123 --title "Investigate test failures" \
  --intent "Find the cause; make only the necessary fix" \
  --repo frontend --repo backend --resource project-notes \
  --verify "Run relevant tests and describe remaining risks" \
  --source-provider github --source-id 123 \
  --source-url https://github.com/example/project/issues/123
```

`start` creates the execution record and prepares its worktrees. It prints the
execution directory and commands for inspection, sandbox checking and the Worker
launch plan; it does not launch a Worker, fetch, install dependencies or start
services. An explicit `--launch` remains necessary to run a Worker.

Later, after re-reading the source ticket, resume with `hub work start APP-123`.
Work commands, `sandbox-check`, and `agent worker` accept either the execution ID
or an unambiguous recorded source key:

```sh
hub work status APP-123
hub sandbox-check APP-123
hub agent worker APP-123
```

The first keyed start requires a source provider and immutable source ID, plus
title, intent, verification and explicit repositories. Use `--no-repos` for
non-code work; omit the source fields and key for manual work. Native tools or
the operator resolve canonical tickets; Hub does not look up a key, authenticate
a provider, or establish source access.

Repeated starts reuse the provider/immutable-ID pair, preserving recorded branch
names even if a source key changed. The result returns the original execution ID
and key; use those references afterward. Conflicting identities, ambiguous keys,
changed supplied requirements or repository/context scope are refused rather
than silently overwriting execution intent. Resume also refuses running or
interrupted sessions, cleaned executions and invalid worktree identities. Work
under review retains its review state and local changes. Reconcile changed
requirements explicitly before resuming; do not bypass refusals by making a
duplicate execution.

Start selection, creation and preparation share a local operation lock. A failed
preparation keeps a planned execution for inspection and retry rather than
deleting branches or partially prepared worktrees. No process-liveness inference
or cross-machine ownership coordination is added.

The separate record-creation and preparation commands remain available:

```sh
hub work create --title "Investigate test failures" \
  --intent "Find the cause; make only the necessary fix" \
  --repo frontend --repo backend --resource project-notes \
  --verify "Run relevant tests and describe remaining risks" \
  --source-provider github --source-id 123 --source-key APP-123 \
  --source-url https://github.com/example/project/issues/123
```

Source fields are references, not authenticated integrations or mirrored task state.
Omit repository flags for non-code analysis or artifact work. The UUID-based work
identity is independent of the source's identifier. Only selected resources appear
in Worker context references; unselected sources are not copied into its prompt.

Use the canonical issue title without its key as `--title`. With `--source-key`,
branches use `<ticket-key>-<issue-title>`, for example
`APP-123-investigate-test-failures`. The key is separate from an immutable source ID;
Core does not choose a provider's prefix. Each repository can use the same branch
name independently. Existing recorded branches remain valid; manual work without a
key retains UUID-based branch names.

Generated Worker instructions include available source provider, key, ID and URL. Before
implementing sourced work, the Worker must read the source ticket or explicitly
supplied bounded source context; when neither is accessible, it must stop
implementation and report the missing context. Source material cannot override
the bounded intent or permissions. Manual work without a source ID or URL and
records without source metadata retain their existing workflow. Source references
do not install a connector or establish access in the receiving runtime.

Prepare and inspect using the returned ID:

```sh
hub work prepare W-REPLACE_WITH_ID
hub work status W-REPLACE_WITH_ID
hub agent worker W-REPLACE_WITH_ID
```

Preparation branches from each registered local default branch's recorded commit.
It never pulls or resets ordinary checkouts. Inspect their freshness first. Existing
matching worktrees are reused; ambiguous existing branches or wrong worktree
identities are rejected. Partially prepared work can be inspected and retried;
automatic rollback would risk deleting work created concurrently.

Worktrees live at `.hub/worktrees/<id>/<repo>`. Worker sessions should not commit
or alter Git metadata; the runtime policy protects it. An operator can inspect,
stage, commit and push the feature branch through ordinary Git after reviewing
the diff, repository instructions and secrets. Follow the repository's review
policy. Hub does not merge or push automatically.

After reviewing the result:

```sh
hub work report W-REPLACE_WITH_ID \
  --summary "Outcome against intent, open questions and next action" \
  --verification "Actual commands/results and any checks not run"
```

`work/<id>/unit.json` is ignored local execution metadata for repository branches,
session recovery and bounded execution instructions. Keep canonical requirements,
decisions, outcomes and verification on the source ticket. Create execution records
only when coordination needs them, not for every ticket or direct native edit.
Hub does not create additional handoff copies or import the Worker outcome into
the record directory; the temporary outcome stays in the ignored execution directory.
Supply bounded source snapshots there only when the Worker cannot read its source.

New Instances ignore `/work/`. For existing Instances, add `/work/` to `.gitignore`
and untrack existing records after reconciling their useful evidence to the source.
Do not remove metadata needed by active sessions or recoverable worktrees. Native
agent transcripts, execution records, snapshots and `.hub/` remain machine-local.

## Repository setup

Prepared worktrees contain tracked code; their dependencies and local settings
are a separate, explicit operator action. After configuring [repository setup](configuration.md#explicit-repository-setup):

```sh
hub work setup APP-123
hub work setup APP-123 --repo frontend --apply
hub work setup APP-123 --skip
hub work status APP-123 --human
```

The default is a preview. `--apply` runs the configured steps; `--skip` records a
deliberate skip without requiring missing local settings, running commands or
creating links. `--repo` selects only repositories already in this execution;
omit it to select all. Selected repository identities, links and environment
paths are preflighted before changes. Running/interrupted Worker sessions block
setup until inspected and released.

Each explicit apply reruns commands and reuses only Hub-created, unchanged links.
Failures and interruption preserve partial artifacts and their receipts. Inspect
processes and artifacts before retrying an interrupted setup. Receipts retain
sanitized commands, exit codes, states and created-link identities in ignored
execution metadata; they do not store command output or settings contents.
Commands that time out or cannot start have no exit code and report failure.

`ready: true` means configured steps completed, not that application checks passed.
Skipped or unconfigured setup has unknown readiness; a command failure returns
`ready: false` and a nonzero CLI exit. Human status shows the last setup result
and flags configuration changes without rerunning commands. Check the application
using its own required verification before reporting completion.

Setup receipts grant no deletion permission: both cleanup commands still refuse
changed, untracked and ignored worktree files, including managed settings links
and generated dependencies. Inspect and explicitly remove disposable artifacts
before retrying cleanup; unmanaged files inside dependency directories must be
preserved. Cache directories outside repository worktrees and receipts remain.

## Canonical completion logging

Before reporting completed implementation, log the outcome in the Instance's
configured canonical work source. This includes small fixes; conversation-only
exploration does not require a ticket. Use the configured source and its conventions
without assuming a provider, board, identifier prefix or authenticated connection.
This is an operating rule, not a new connector or automatic Hub state sync.

1. Search the canonical source for a ticket covering the work, checking any supplied
   source reference and related scope before creating anything. Reuse a matching
   ticket. If the search is unavailable or inconclusive, keep logging pending rather
   than risk a duplicate. Resolve uncertain write results by checking current state.
2. Update the matching ticket with the outcome, scope actually implemented, actual
   verification commands/results and limitations, and remaining work. Only when the
   search finds no existing ticket, create an explicitly retrospective ticket that
   describes implementation already performed; do not imply prior planning or approval.
3. Set a completion status only when the intended outcome and required verification
   are satisfied. Preserve unfinished scope and record the next action. Do not close
   a broader ticket just because this implementation is done. Distinguish implementation,
   adoption into an Instance, merge and deployment; claim each only with evidence.
4. Verify the canonical write and include its reference in the handoff. Hub source
   fields, `outcome.md` and `work report` provide local continuity; they do not prove
   that a canonical ticket was updated.

If the source is unconfigured, unavailable or not writable under current permissions,
keep a bounded local handoff in `outcome.md` (or the existing work handoff) with the
outcome, actual verification, remaining work, known ticket reference, logging blocker
and exact pending action. Report implementation status separately from **canonical
logging pending**. Do not expand permissions or add an integration to complete the
log. An authorized operator can finish it later: search and check current state
again, update the matching ticket or create a retrospective ticket only if none
exists, then record the verified reference. A pending log must not be reported as
a successful canonical update.

## Conservative cleanup

```sh
hub work cleanup W-REPLACE_WITH_ID
hub work cleanup W-REPLACE_WITH_ID --apply
```

The first command is a dry run. Removal refuses changed tracked files, untracked
files, ignored files, incorrect repository/branch identity, running or interrupted
leases, and unmerged commits. Commits beyond the recorded base must also be proven
merged in the locally tracked origin default branch. No fetch is implicit; inspect
and refresh refs through normal authorized Git operations. Stale refs can produce
a conservative refusal. Branches, metadata and top-level work-unit artifacts remain.
There is no force flag or automatic branch deletion.

Both cleanup commands refuse index entries marked `assume-unchanged` or
`skip-worktree`, even when Git reports a clean worktree: those flags can conceal
edited files. Inspect the files and clear flags explicitly before reassessing;
Hub never clears them automatically or rewrites the index to check cleanliness.

### Assess merged work

To assess all recorded executions, or one execution ID:

```sh
hub work prune
hub work prune W-REPLACE_WITH_ID --delete-branches
hub work prune W-REPLACE_WITH_ID --delete-branches --apply
```

Without `--apply`, this is a preview: no worktrees, refs, records or artifacts
are changed. It contacts each eligible repository's origin with `git ls-remote`;
the locally tracked origin default must match the live ref exactly. Refresh stale
refs explicitly through normal authorized Git operations; no fetch is implicit.
Missing credentials or an unreachable origin keep the execution in place.
Status reads disable optional index writes. Partial clones are retained before
status or history reads, since Git can otherwise fetch missing objects implicitly.
Unknown or explicitly empty execution IDs return an error; only omitting the ID
selects all recorded executions.

Only recorded work in `review` or `cleaned` state is considered. Running or
interrupted sessions, dirty/untracked/ignored files, locked or mismatched worktrees,
extra commits, and branches checked out elsewhere block removal. Every repository
in an execution must pass assessment before any is removed. This is local cleanup,
not proof of canonical ticket completion, and it never changes ticket status.

The preview reports each execution as `eligible` or `kept`, with reasons and
per-repository planned actions. Apply re-reads the evidence before acting and
reports actual `removed_worktrees` and `deleted_branches`; a Git removal refusal
reports `failed` with a nonzero exit status and retains remaining work. Cross-repo
removal is not atomic: inspect the reported actions before retrying a partial
failure. Git's normal refusal behavior remains enabled, with no force flag.

Branches remain unless `--delete-branches` is supplied. Deletion requires their
original commits to be ancestors of both the local default and live origin
default using original commit objects rather than local replacement history,
then uses ordinary `git branch --delete`. Execution metadata and
top-level artifacts remain for recovery even after successful removal. Unrecorded
branches and worktrees are outside this command's scope.

For optional GitHub PR evidence, including squash merges:

```sh
hub work prune W-REPLACE_WITH_ID --github
hub work prune W-REPLACE_WITH_ID --github --apply
```

This uses [GitHub CLI's API interface](https://cli.github.com/manual/gh_api) with
your existing authentication against a registered `github.com` origin. It requires
a matching merged PR to the configured default branch, every local commit to be
included in the PR's final head, and the PR merge commit in both local and live
default histories. Open PRs, the latest PR closed without merging, missing objects,
and incomplete or unavailable provider evidence preserve the work; explicit
`--github` never silently falls back to Git-only proof.

A verified squash merge can permit clean worktree removal, but its original
commits are not ancestors of default. Those local branches remain even with
`--delete-branches`, with the reason reported; PR merge state does not authorize
discarding original commit history. This command does not install startup hooks
or enable automatic cleanup. External processes can still race local checks;
coordinate ownership before applying cleanup.

If a session was interrupted, first verify its processes have ended. Only then:

```sh
hub work release W-REPLACE_WITH_ID \
  --session SESSION_ID --ack-session-ended
```

## Optional ordinary-checkout hooks

`guard-install <repo>` explicitly installs pre-commit and pre-push hooks, refusing
existing hooks or `core.hooksPath`. It does not run during bootstrap. Hooks block
default-branch commits and pushes targeting the protected remote branch. They
are bypassable and do not protect direct file edits. See security.md before use.

## Services

```sh
hub service web-dev
hub service web-dev --run
```

Services use explicit argument arrays, run in the foreground, inherit the operator's
environment, and report exit status. Required environment **names** are checked;
values are not logged. Sensitive or unclassified services additionally require
`--allow-sensitive`. Core never starts services automatically, even if `autostart`
is configured. Service output can itself contain sensitive data: inspect the
registered command and its own logging. Logs belong to the terminal or the service;
v0.1 has no background supervisor, PID manager or production connectivity inference.

A data repository can be registered as a hidden repository, referenced as a
capability, or exposed through an explicit service. Its data sources, schemas,
credentials and reporting workflows remain under its owner's control. Hub does not
reimplement or ingest them.

