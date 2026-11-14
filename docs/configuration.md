# Configuration

Shared `hub.toml` and `repos.toml` express intent. `core.lock` pins the public source
and exact commit. Ignored `local.toml` resolves machine details. `.hub/` holds
generated workspaces, installed Core checkouts, logs, worktrees and probes.

Precedence: shared Hub config → optional external overlay → local overrides.
Tables merge recursively. Resources merge by name; an override changes an existing
resource rather than duplicating it. Repository definitions come from `repos.toml`;
`[repos.<name>].path` is a local/overlay attachment override. Relative overlay
resource paths resolve against the **Instance**, not the overlay's directory.

```toml
schema_version = 1

[instance]
name = "example"
purpose = "Coordinate product work"

[agent]
runtime = "codex"
```

Repository fields:

| Field | Meaning / default |
| --- | --- |
| `name` | Unique registry name; letters, digits, `_`, `-` |
| `folder` | Relative folder below resolved `paths.repos_root`; defaults to name |
| `remote` | Expected origin; credentials and query strings forbidden |
| `default_branch` | Expected local default branch; `main` |
| `protected` | Reject protected branches for Workers; `true` |
| `checkout` | Clone if absent during bootstrap; `false` |
| `description` | Optional purpose |
| `visible` | Include an available repository in the workspace; `true` |

Registration is not availability. A directory is available only when it is the
repository root, origin matches, and the expected local default branch exists.
Visibility only changes the generated workspace. Bootstrap never switches branches,
resets changes, rewrites origins, or installs hooks in existing checkouts.

Default repositories are siblings of the Instance. Existing paths can be attached
through local overrides. Nested or duplicate managed destinations are rejected.
Core may be registered like any repository. Its editable checkout is distinct from
the pinned runtime under `.hub/cores/`.

Resources use `[[resources]]` entries:

| Field | Meaning |
| --- | --- |
| `name`, `kind` | Identity; kind is context, capability, tool, mcp, work or service |
| `purpose` | Why this resource exists |
| `path` or `location` | Local path or external reference; no ingestion |
| `runtimes` | Applicable providers (descriptive in v0.1) |
| `dependencies` | Required tools/resources (descriptive; no installation) |
| `usage` | Invocation instructions; not automatically executed |
| `executable` | CLI whose local presence can be checked |
| `repo`, `command` | Service repository and argument array; never implicit shell text |
| `environment` | Required variable names; values never reported |
| `preview_url` | Optional development preview reference |
| `autostart` | Recorded preference; always disabled in v0.1 |
| `sensitive` | Service needs extra execution opt-in; defaults to true |

A resource with a local path can be available without being connected. A registered
MCP server or work provider remains unverified until checked in its native client.
There are no automatic authentication checks, network probes, dependency installs,
or user-home scans. Do not embed secrets in commands or URLs.

Example local overlay reference (placed before other TOML tables):

```toml
overlay = "/approved/private/location/personal.toml"

[paths]
repos_root = "/approved/projects"
```

`HUB_OVERLAY` is used when `local.toml` does not specify an overlay. Overlay content
is never copied into shared configuration. Config does not grant authorization to
read the referenced source. See the complete examples in `templates/instance/`.

