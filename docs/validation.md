# v0.1 validation

Validated locally on 2026-11-14 using macOS arm64, Python 3.13.11 and Git 2.50.1.
The available desktop-bundled CLI was Codex 0.146.0-alpha.9.2. VS Code 1.145.2 and
the OpenAI extension were installed. Linux/Python 3.11 CI is configured but has not
been executed as part of this local build.

## Automated checks

`python3.13 -m unittest discover -s tests -v`: **67 tests passed**. The full suite
also passed when run from a separately installed candidate Core during adoption.

Coverage includes:

- Fresh and repeated initialization; independently owned Git history; nonempty
  destinations refused; malformed configuration, duplicate destinations and unsafe
  paths rejected; external overlay references preserved.
- Existing repository attachment, wrong origin/root, explicit local cloning and
  repeated bootstrap; registration/availability/visibility kept distinct; generated
  workspace tasks use the pinned Core and process argument arrays.
- Single/multiple-repository and non-code work; original checkout unchanged after
  worktree edits; branch changes and tampered metadata detected; preparation is
  repeatable; work and handoffs recover independently of sessions.
- Default-branch commit and protected-target push hooks; existing hooks preserved;
  cleanup dry run and explicit apply; changed/untracked/ignored files, unmerged
  commits, unpushed local commits and active/interrupted leases refused. Branches
  and metadata remain after allowed cleanup.
- Codex launch policy construction, session completion/interruption and handoff
  lifecycle with mocked provider execution; failed sandbox preflight prevents
  execution; legacy permission conflicts refused; logs discard provider payloads;
  credential-bearing outcomes are refused on import.
- Adoption and rollback, failed candidate tests, incompatible schemas, stale lock
  conflicts and modified installed Core; reconciliation's four classifications and
  read-only behavior; promotion blocked without disclosure rights; secret detection
  and output redaction without credential values.

The heuristic scanner passed against the final Core files and staged selection.
This is not a comprehensive secret audit or an ownership authorization.

## Separate Instance and self-hosting experiment

An independent local Instance was initialized from a committed Core snapshot. It
attached five available existing repositories plus an editable Core repository.
The generated workspace showed only the Instance and Core; the other repositories
remained available but hidden. Context and skill directories were registered as
references without ingesting their contents. The external work source was correctly
reported as unsupported/unverified. The Instance's Core was a separate detached
checkout, not its editable source repository.

The Orchestrator operating instructions and read-only launch plan were generated.
A bounded work unit prepared an isolated Core worktree. A real Worker, using the
development session's available agent tools, improved diagnostics, added five tests
and wrote its outcome while the primary agent continued working. The Worker suite
passed 58 tests. The operator reviewed the three-file diff and imported the handoff.
The original editable Core and installed runtime stayed unchanged during Worker
execution. Subsequent security checks brought the integrated suite to 67 tests.

A new Core commit was proposed and adopted into the separate Instance. Candidate
tests, configuration checks and diagnostics passed. Rollback restored the previous
Core, and a second explicit rollback restored the adopted version. Shared Hub
configuration, repository registry and local overrides remained byte-for-byte
unchanged. The self-hosting worktree and its reviewable changes were preserved.

A structured reconciliation assessment and a general, authorized promotion proposal
were prepared within the Instance. No private implementation was inspected. No
Instance context or configuration was exported into public Core, and nothing was
published. User-specific discovery roots remain in the personal setup prompt, not
Core defaults; those additional roots were not scanned during this build.

## Runtime and host limitations

The native Codex sandbox probe returned exit 71: the host refused nested Seatbelt
sandbox creation (`sandbox_apply: Operation not permitted`). The CLI Worker launch
therefore stopped before a model session and did not fall back to unrestricted
execution. Doctor reports installed prerequisites as ready but sandbox evidence as
blocked and Worker execution as unverified.

The real session-tool Worker proves the isolated Core development and handoff flow;
it does **not** verify the separate CLI adapter's end-to-end execution or filesystem
enforcement. Native interactive/noninteractive Codex sessions need a validation run
on a host that permits their sandbox. Native VS Code panel layout, GUI workspace
opening and process restoration remain manual/unverified here. No cross-provider
or authenticated remote connector support is claimed.

The development sandbox also refused creating `.git` in the supplied source
directory. Separate temporary Core and Instance Git repositories were used for
version and lifecycle checks. A Core-only Git bundle preserves local Core history
for cloning into a normal Git-enabled location. The supplied source files remain
editable; remote creation, visibility changes and pushing remain unapproved.

## Claude Code provider addition (proposed)

The new Claude adapter's launch-plan construction, fail-closed behavior,
runtime-specific diagnostics, and session metadata are covered by automated
unit tests with mocked Claude process execution. The real authenticated Claude
CLI and its operating-system sandbox are **not available or validated** in this
development session. The model-assisted preflight requires a supported local
host, verified authenticated Claude runtime, and a disposable work unit before
any production use. GitHub CI provides Python test evidence, not Claude
end-to-end security verification. The earlier v0.1 validation facts above
describe the earlier baseline; they are not a claim that the new adapter ran
in the original validation environment.
