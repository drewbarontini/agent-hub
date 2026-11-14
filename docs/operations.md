# Operations

Run commands from the Instance using Python 3.11+:

```sh
python3.13 .hub/bin/hub status
python3.13 .hub/bin/hub doctor
python3.13 .hub/bin/hub resources
```

## Bounded work

```sh
python3.13 .hub/bin/hub work create --title "Investigate test failures" \
  --intent "Find the cause; make only the necessary fix" \
  --repo frontend --repo backend --resource project-notes \
  --verify "Run relevant tests and describe remaining risks" \
  --source-provider github --source-id 123 \
  --source-url https://github.com/example/project/issues/123
```

Source fields are references, not authenticated integrations or mirrored task state.
Omit repository flags for non-code analysis or artifact work. The UUID-based work
identity is independent of the source's identifier. Only selected resources appear
in Worker context references; unselected sources are not copied into its prompt.

Prepare and inspect using the returned ID:

```sh
python3.13 .hub/bin/hub work prepare W-REPLACE_WITH_ID
python3.13 .hub/bin/hub work status W-REPLACE_WITH_ID
python3.13 .hub/bin/hub agent worker W-REPLACE_WITH_ID
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
python3.13 .hub/bin/hub work report W-REPLACE_WITH_ID \
  --summary "Outcome against intent, open questions and next action" \
  --verification "Actual commands/results and any checks not run"
```

Commit appropriate `work/<id>/unit.json` and handoff files to the independently
owned Instance if continuity between machines matters. Inspect imported outcomes
for private content before sharing. Native agent transcripts and `.hub/` remain local.

## Conservative cleanup

```sh
python3.13 .hub/bin/hub work cleanup W-REPLACE_WITH_ID
python3.13 .hub/bin/hub work cleanup W-REPLACE_WITH_ID --apply
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
python3.13 .hub/bin/hub work release W-REPLACE_WITH_ID \
  --session SESSION_ID --ack-session-ended
```

## Optional ordinary-checkout hooks

`guard-install <repo>` explicitly installs pre-commit and pre-push hooks, refusing
existing hooks or `core.hooksPath`. It does not run during bootstrap. Hooks block
default-branch commits and pushes targeting the protected remote branch. They
are bypassable and do not protect direct file edits. See security.md before use.

## Services

```sh
python3.13 .hub/bin/hub service web-dev
python3.13 .hub/bin/hub service web-dev --run
```

Services use explicit argument arrays, run in the foreground, inherit the operator's
environment, and report exit status. Required environment **names** are checked;
values are not logged. Sensitive or unclassified services additionally require
`--allow-sensitive`. Core never starts services automatically, even if `autostart`
is configured. Service output can itself contain sensitive data: inspect the
registered command and its own logging. Logs belong to the terminal or the service;
v0.1 has no background supervisor, PID manager or production connectivity inference.

Data Desk can be a hidden registered repository, a capability reference, or an
explicit service. Its data sources, schemas, credentials and reporting workflows
stay with Data Desk. Hub does not reimplement or ingest them.

