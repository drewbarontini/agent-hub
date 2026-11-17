# Operations

Run commands from an initialized Instance with its local `hub` launcher
on your session PATH (see [Instance CLI](getting-started.md#use-the-instance-cli)).
The launcher still requires Python 3.11+ as `python3`:

```sh
hub status
hub doctor
hub resources
```

## Bounded work

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

