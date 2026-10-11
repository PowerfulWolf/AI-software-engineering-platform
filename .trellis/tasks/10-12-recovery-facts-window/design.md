# Approved design

Root read and approved this PRD/design/spec before production implementation. The
authentic six-read red was then established before implementing the window.

## Supported route and compatibility

Use a private selector inside `NativeRecoveryFactsVerifier.inspect`: only exact standard
Native `_inspect` composition, a nonempty plan workspace snapshot and no quarantined paths
select the new window. A frozen standard `_inspect` function reference must distinguish
instance/class/subclass stronger overrides; all other inspectors execute their existing
two `_inspect` calls. Preserve the separately root-owned `_STANDARD_NATIVE_VALIDATE` alias.
Accepted progress, legacy missing policy/snapshot, and quarantined capture remain on the
original route. `coder_reapply` retains its complete source capture/input semantics.

## Window ordering

```text
readonly Team/Project/Repository resolution
existing old Worker lock acquisition (no create, no global SQL authority lock)
  full source-before
  full target-before
  terminal-before: fresh routes/start/stop/invocation/SQL + capture + actual stop + inventory
  full source-after
  full target-after
  terminal-after: fresh routes/start/stop/invocation/SQL + capture + actual stop + inventory
  compare full source/target/terminal facts and complete inventory/ignored/tracked sets
  require each snapshot equals the immutable approved Plan snapshot
existing lock/root inode checks and release
return existing NativeRecoveryFacts shape
```

The second terminal pass consumes its own newly read stop and SQL facts. It cannot rely
on the first pass's stop object, a earlier SourceReader result, or cached terminal success.
No await/model/dispatch callback occurs in this context. Scope ownership is synchronous,
single owner and ends on success/failure; a closed/foreign window is not usable.

## Current target extraction

Factor existing target logic into a private preflight and completion, retaining its old
ordering for compatibility: source -> target preflight -> public terminal wrapper ->
target completion. Supported window calls preflight+completion as one full target pass
before its separate terminal pass. The preflight retains team/project/sidecar ownership,
preparation/profile, target authorization, branch, scope supplement and permission checks.
Completion retains complete binding/no-symlink/environment validation, current Team/
Project knowledge selections, rules compiler/integrity/source URIs, repository/filter
checks, HEAD/clean/ancestry and original capture verification. No target result crosses
its individual pass or is silently reused for target-after.

## Terminal extraction and safe public wrapper

Add an internal context-owned terminal reader below the public wrapper. A single read
returns complete typed terminal facts, verified snapshot and the complete observation;
it freshly checks existing SQL decoders, request permissions/revision, stop, routes,
supplement, capture and inventory. Keep `read_terminal_workspace_snapshot` as the existing
safe independently callable API, owning its lock and two full source reads and both
terminal observations. Accepted-progress/legacy branches and error translation remain.
Extract only shared lower audit logic; no public `skip_source` option or caller-supplied
approved/current facts. New context is private Python composition, not Schema/tool/API.

## Validation dependency

`tests/recovery/test_execution.py` supplies the authentic modern native fixture and Root
authorized necessary incremental MySQL use in exclusively owned
`ai_software_engineer_test`, with exact database/session/initial-empty validation and
finally owned-process termination/13-table-empty cleanup. Production database access is
forbidden. Existing
`test_workspace_snapshot._composition` replaces the source and Team with casts and is
insufficient for new acceptance. New `test_facts_window` must persist real approved stage,
Context/route/start/stop/capture/native workspace records and use real test SQL or typed
isolated SQL rows through actual native/terminal decoders. It must run actual Native source and full target
code, not return an invented high-level source/facts object. This fixture construction is
the first implementation checkpoint; inability to complete it is reported, not hidden.
