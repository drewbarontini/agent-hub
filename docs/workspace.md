# VS Code workspace

`workspace` generates `.hub/hub.code-workspace` with the Instance and only available,
visible repository roots. Hidden repositories remain in the registry and can be
used for worktrees. Regeneration uses resolved local paths; the file is ignored.

Generated tasks use argument arrays with VS Code's `process` task type. They provide
status, doctor and an explicit Orchestrator launch. No service or agent runs on
folder open. Repository-defined tasks are also available through normal VS Code
multi-root behavior; review their commands before running them.

Suggested arrangement:

1. Open Codex in a sidebar for Orchestrator conversation, or run the read-only CLI
   Orchestrator task in a terminal editor.
2. Run independent CLI Workers in separate terminals, with one work unit per session.
3. Move Worker terminals into editor groups; keep source, diffs and previews beside them.

The installed OpenAI extension may offer “New Codex Agent” panels as well. These
panels are optional. Set each panel's working directory and permissions explicitly;
Hub does not control native panel sandboxes or attach its session leases to them.
The CLI launch path provides deterministic directories and a fail-closed probe.

A workspace file does not guarantee sidebar placement, panel grouping, simultaneous
native agent execution or restoration of running processes. VS Code usually stores
editor state locally; that is not portable Hub state. Work handoffs survive session
termination independently. Code extension presence and actual agent authentication
are distinct checks. Opening the generated workspace is a manual verification step
when the host cannot launch a GUI from the execution environment.

Sources checked during v0.1 implementation:

- [VS Code multi-root workspaces](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces)
- [VS Code terminal editors](https://code.visualstudio.com/docs/terminal/basics)
- [Codex IDE commands](https://learn.chatgpt.com/docs/ide/commands)

