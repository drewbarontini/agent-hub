# Adopt, Reconcile, Promote

Instances are environments for experimentation and application. Core contains
what has been generalized and approved for reuse. Not every local improvement
belongs in Core.

## Adopt: Core → Instance

The `hub` examples below assume you are in the initialized Instance with its
local launcher on PATH (see [Instance CLI](getting-started.md#use-the-instance-cli)).

From the Instance, inspect an explicit release/ref first:

```sh
hub adopt --ref v0.1.1
# During local development, also pass --source /approved/core-checkout.
```

The plan resolves a full commit, inspects version/schema information, lists commit
summaries, detects incompatible schemas or unrelated histories, and describes
validation/rollback. Inspect the actual candidate diff and release notes too. No
target code runs in planning mode. Network access is needed for a remote source;
credentials remain Git's responsibility. There is no automatic update polling.

```sh
hub adopt --ref v0.1.1 --apply
hub rollback
```

`--apply` authorizes candidate code execution: a separate detached checkout is
installed, its tests run, and its CLI parses current configuration. Current required
diagnostics must pass. Only then does Core switch the lock, regenerate workspace
tasks/instructions and run candidate diagnostics. Failure restores the previous
lock. A previous lock and both installations remain for rollback. Shared Hub
configuration, repository registry, overlays and context are not rewritten.

Review and commit `core.lock` after adoption. Generated paths and rollback files
stay local. v0.1 supports one previous-lock rollback slot; retain older commits in
Instance Git history. Core commits must remain reachable for future reinstalls.

## Reconcile: existing Hub ↔ Core

Start with authorization to inspect the existing Hub. Do not assume access to
private organizational implementations. Inventory behavior without copying source:

```sh
hub reconcile --inventory /approved/capabilities.toml
```

Use `templates/reconcile.toml`. The command reads only that supplied inventory and
Instance configuration; it never traverses implementation files. Its JSON report
classifies differences as Adopt, Preserve, Promote candidate or Retire, and includes
Core equivalents, missing functionality, ownership, conflicts, provider concerns,
migration sequence, verification and rollback. Classifications are initial review
suggestions based on inventory fields, not automated parity judgments.

Without an inventory, it reports what Core provides and identifies existing
behavior as not inventoried. This is an honest starting assessment, not a claim
to have inspected or understood a private Hub. Output goes to stdout; redirect it
to an approved location when a saved report is wanted. Reconciliation is read-only.

### Existing organizational Hub procedure

1. Record the existing commit, local changes, running services, active worktrees,
   authoritative context and credentials' locations. Preserve its working entry points.
2. With authorization, inventory `repos.toml`, bootstrap, status, worktree, service,
   guard and instruction behavior. Note ticket conventions, external work providers,
   native agent hooks, skills and MCP configuration without exporting their contents.
3. Compare with Core. Preserve private repositories, team policies, work-provider
   ownership, data repository and personal overlay references in approved locations.
4. Initialize a new Instance alongside the existing Hub. Pin Core and translate
   configuration. Keep the existing Claude runtime until a separately tested adapter
   meets its native permission and instruction requirements.
5. Verify clone/attachment identity, workspace visibility, multi-repository tasks,
   default-branch safeguards, dirty/unmerged cleanup refusals, service environment,
   skills, private work sources and personal context access with disposable tasks.
6. Switch entry points only after review. Retire duplicates only after replacements
   pass parity checks. Roll back by restoring the existing entry points and commit;
   do not delete old worktrees or move private context during migration.

This is the intended path for a Team Instance with a personal overlay in an
approved location. v0.1 does not perform that migration or claim private access.

## Promote: Instance → Core

```sh
hub promote \
  --problem "A general problem that is permitted to disclose" \
  --requirement "Reusable public behavior" --ownership unknown
```

This creates a structured prose proposal on stdout. It accepts no patch, source
directory or implementation file. Unknown, personal or organizational ownership
alone does not establish publication permission. Such proposals are blocked pending
ownership and disclosure review. `--ownership approved-for-public
--disclosure-authorized` marks a proposal ready for human review; it still publishes
nothing and is an operator attestation, not a legal determination.

Before passing even prose to this command, determine that the problem and design
may be recorded in the Instance. Organizational ownership and confidentiality can
restrict the idea as well as the source. Removing names or independently rewriting
code is not a way around those restrictions. Keep blocked proposals in an approved
location; never automatically transfer them to a personal repository or service.

After authorization, implement the generalized requirement in an isolated Core
worktree, using public fixtures and permitted inputs. Review tests, source rights
and the resulting change. Obtain separate explicit approval before creating an
external pull request, pushing, publishing, or changing repository visibility.
