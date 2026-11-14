# Security and ownership

Core must stay public and reusable. Instance configuration belongs to its owner.
Personal overlays belong in an approved private location. Referencing a resource
does not authorize reading, exporting, or publishing its contents.

| Safeguard | Enforced behavior | Limits |
| --- | --- | --- |
| Repository identity | Actual Git root, origin and default branch checked | Does not establish ownership or remote authorization |
| Worker branch validation | Wrong branch, default branch, detached or wrong worktree refused | External processes can still modify repositories |
| Worker permission policy | Explicit work-unit writes, read-only Git metadata and ordinary checkouts, command network disabled | Requires supported native runtime/OS; excludes external tools and approvals |
| Sandbox preflight | Inside write succeeds; outside and `.git` write opens fail, or launch is blocked | Representative checks, not proof against every escape |
| Optional Git hooks | Default commits and protected-target pushes refused | `--no-verify`, `git -c core.hooksPath=...` and direct edits bypass hooks |
| Cleanup | Dirty, untracked, ignored, unmerged, extra local commits and active/interrupted leases refused | No distributed liveness detection or atomic protection against unrelated processes |
| Secret scan | Known credential patterns, selected private/generated files and external symlinks flagged without showing values | Heuristic; cannot establish disclosure rights or find every secret |
| Evolution | No Instance implementation export; adoption stages Core separately | Candidate tests execute code only on explicit apply; source must be trusted |

The development host rejects nested sandbox creation. Thus runtime protection is
implemented with a fail-closed probe but not claimed operationally verified on this
host. Tests exercise guard behavior and probe failure; see validation.md. Do not
disable sandboxing, use full access, or grant ordinary checkouts write access merely
to make a Worker launch succeed.

Codex's adapter uses explicit paths so system temp directories are not
implicitly writable. Claude's native sandbox uses different defaults, including a
per-user temp directory, and must not be described as the same policy. Its strict
Worker launch uses `--restricted`, native sandbox requirements and file-tool
path checks, with a separate probe before execution. The probe may incur model
usage charges and is not yet validated on a supported host. The probe checks
representative outside and Git metadata paths, not a complete security boundary.
A native IDE agent launched outside Hub does not inherit either CLI policy. Neither a worktree nor a prompt is a security boundary by itself.

The command filesystem sandbox does not isolate provider-native MCP tools,
connectors, browser actions, computer use, inherited credentials or all read access.
Worker context selection narrows references in its prompt; it is not a confidentiality
firewall. Use separate accounts, runtime homes, provider controls or stronger OS
isolation where information access must be enforced. v0.1 does not provision them.

Never commit secrets. Git ignore rules reduce mistakes but do not prevent forced
adds, shared logs or exports. Run `secrets` and `secrets --staged` from the relevant
repository, inspect staged diffs, and use your organization's approved credential
and secret-scanning tools. Scanner findings identify files, never matched values.
Core does not read auth files or credential stores. Git and the runtime resolve
their own authentication. Do not place credentials in URLs, commands or config.

Service commands can run arbitrary programs and inherit operator credentials.
Inspect their definitions before opting in. `sensitive=false` is a configuration
assertion, not automated proof that a service is disconnected from production.
Services never autostart, and unclassified/sensitive services need an additional
explicit flag. Their own output is outside Hub's credential-redaction guarantee.

Use only authorized information in reconciliation inventories and promotion prose.
Organization-owned source and designs do not become publishable after names are
removed. If ownership or disclosure is uncertain, stop the export and retain a
blocked proposal with its owner. Publishing Core, changing visibility and pushing
code require explicit approval. Core has no publication command.

