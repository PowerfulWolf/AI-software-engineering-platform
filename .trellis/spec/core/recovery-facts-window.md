# Synchronous modern terminal observation window

## Scope and signatures

Applies only to modern failed terminal recovery with a complete plan-bound workspace
snapshot, standard Native composition and no quarantined paths. Production files:
`src/ai_software_engineer/recovery/current.py` and
`src/ai_software_engineer/recovery/workspace_snapshot.py`.

```python
NativeRecoveryFactsVerifier.inspect(plan: RecoveryPlan) -> NativeRecoveryFacts
NativeRecoveryFactsVerifier._inspect(plan: RecoveryPlan) -> NativeRecoveryFacts
# Internal target and terminal composition.
NativeRecoveryFactsVerifier._target_preflight(
    plan: RecoveryPlan, original: NativeRecoverySource,
) -> _RecoveryTargetPreflight
NativeRecoveryFactsVerifier._target_facts(
    plan: RecoveryPlan, preflight: _RecoveryTargetPreflight,
) -> NativeRecoveryFacts
_terminal_workspace_window(
    config: ProductionConfig, environment: Mapping[str, str], source: RecoverySource,
) -> ContextManager[_TerminalWorkspaceWindow]
_TerminalWorkspaceWindow.observe(
    original: NativeRecoverySource, capture: CapturedChanges, *,
    permissions: AgentPermissions, supplement: RecoveryScopeSupplement | None,
) -> _TerminalWorkspaceRead

@dataclass(frozen=True)
class _TerminalWorkspaceRead:
    facts: TerminalWorkspaceFacts
    observation: TerminalWorkspaceObservation
    snapshot: RecoveryWorkspaceSnapshot

read_terminal_workspace_snapshot(
    config, environment, original, capture, *,
    approved_permissions=None, scope_supplement=None,
) -> RecoveryWorkspaceSnapshot | None  # unchanged independent safe wrapper
```

These are internal synchronous Python contracts. No public skip flag, JSON schema,
serialized receipt, Agent tool, claim or persistent authorization is introduced.

## Ownership, ordering and full comparison

Resolve the current registered Team/Project/Repository read-only and acquire the existing
old Worker lock before the first complete source read. Keep its regular-file, private
mode, nonblocking flock, lock inode and directory identity checks; do not create/replace
locks, initialize queue/schema or reacquire global MySQL authority locks.

Within that scope execute complete source-before, complete target-before and complete
terminal-before, then complete source-after, complete target-after and complete
terminal-after. Each source uses the unchanged full NativeRecoverySourceReader, including
its native lineage, baseline/context, retirement, route, approval and own before/after
SQL/journal checks. Each target reruns full preparation/profile/authority/branch/supplement/
permissions, binding/environment, knowledge selection/rules compilation/integrity and Git
repository/filter/HEAD/clean/ancestry/capture checks. The terminal observer reads new
start/stop/invocation/routes and consistent read-only SQL facts, verifies capture and real
owned stop, observes full bounded no-follow inventory and applies the existing pure audit.

The second terminal SQL/stop/capture/inventory pass must occur after both final source
and final target checks. Compare complete sources, target facts and terminal facts, plus
inventory, ignored paths and tracked environment sets (observation clock is not identity).
Require both derived snapshots equal the exact Plan snapshot. Any drift rejects before
return; no stale result survives an error. Lock exit validates identity before success.

An owner/closed-window guard prevents using the private observer outside its context.
The scope requires exactly two successful terminal observations before normal exit,
rejects a third and rejects foreign thread/async-task use before reading SQL. Complete
terminal observations are freshly constructed, including independent stop model objects.
No data crosses a later Native inspection, builder, dispatch fence, seed, role claim or
model admission. Two observations detect observed drift; they are not a distributed
transaction, Git lock or general OS sandbox.

## Compatibility and validation matrix

Legacy, accepted-progress, quarantine and custom/overridden `_inspect` compositions retain
the original two observations and independently safe public terminal wrapper. Standard
delegate identity is frozen; exact class identity alone must not skip a stronger instance
or class method. The separately defined standard Native `validate` reference is retained.

| Input / event | Required behavior |
| --- | --- |
| Actual supported modern failed Native inspection | Exactly two full SourceReader calls, two complete target passes, two terminal SQL/stop/capture/inventory passes |
| Mutation during final source/target pass | Final terminal rereads and complete comparisons reject; no Task/approval/claim effect |
| SQL raw/payload, status/claim/lease/baseline drift | Original decoders or complete terminal comparison reject |
| Changed/missing stop, live owned process, changed capture or ignored inventory | Stop/capture/inventory checks reject after final source |
| Old Worker lock busy/missing/symlinked/replaced | Reject; never create or replace it |
| Prepared target/profile/binding/rules/knowledge/HEAD/clean/filter/ancestry drift | Second complete target pass rejects |
| Accepted terminal progress / no original interruption policy / quarantine | Original safe path, unchanged snapshot/None semantics |
| `_inspect` subclass, class or instance stronger override | Original complete path; never bypass its checks |
| Closed/foreign owner window | Reject; no previous facts used as authority |
| Missing second observation / third observation | Reject; no one-observation success or unbounded locked loop |
| Success/failure | Lock released, no current-facts cache retained |

Good: actual modern stopped failure yields the identical plan-bound snapshot and existing
NativeFacts shape with two full source passes. Base: unsupported modes execute the old
independent safe composition. Bad: pass an earlier supplied source into a wrapper that
skips its two native reads, or omit stop/capture/inventory after the final complete source.

## Required tests and deployment

`tests/recovery/test_facts_window.py` must first demonstrate actual Native six-reader
behavior, then two-reader behavior with a valid complete native lineage. Use real
temporary Git, file stores, artifacts, existing private lock and owned process-stop facts;
only isolated SQL/OS transport ports may be substituted. High-level Source/Facts casts do
not establish acceptance. Assert late source/target/SQL/stop/capture/inventory mutations,
lock failure, unchanged legacy/progress/quarantine results and exact delegate fallback.
Keep existing workspace snapshot/plan, source and Native compatibility regressions; run
only necessary increments, Ruff, format, strict Mypy and diff checks.

Necessary authentic MySQL increments use exclusively owned `ai_software_engineer_test`:
validate the exact database, no other sessions and 13 mutable tables empty before the
fixture; finally stop owned offline processes and return every table to empty before
releasing ownership. Never connect, initialize, reset or write `ase_self_iteration`.
`tests/recovery/facts_window_fixture.py` owns this bounded test composition; it retains
actual TeamHost/Worker, approved native file lineage and read-only SQL decoders.
Real cases keep `@pytest.mark.mysql`; `test_facts_window.py` locally overrides the global
`isolated_mysql_facts` autouse reset with an empty yield. The global setup hook still
rejects unsafe DSNs, while the helper performs all resets only inside its exclusive
admission window. `-m 'not mysql'` must deselect these tests and never connect to MySQL.
Do not add the mysql marker without this override: the global reset would run before
the exclusive gate and could clear another fixture. Simulated occupied execution uses
only the `_SessionInspector` OS transport seam; the original stop proof, Native chain,
auditor and complete source/target validators still execute.

Executable increments:

```sh
PYTHONPATH=src python -m pytest -q tests/recovery/test_facts_window.py
PYTHONPATH=src python -m pytest -q -m 'not mysql' \
  tests/recovery/test_workspace_snapshot.py \
  tests/recovery/test_terminal_source_inspection_scope.py \
  tests/recovery/test_workspace_plan.py tests/recovery/test_scope.py \
  tests/recovery/test_current.py
```

See the task's `verification.md` for the actual six-read red, individual green runs,
typed checks, exact helper cleanup and the timing interpretation boundary.

`tests/recovery/test_window_task_builder.py` additionally composes the real modern fixture,
Git capture, exact FileRecoveryStore authorization and AuthorizedRecoveryTaskBuilder. A
standard build retains four complete Native inspections with eight fresh source reads;
it does not publish a Task. Removing the real stop record after pure Task derivation must
make the final authorization window reject while Plan/authorization bytes stay unchanged.
This module uses the same mysql marker and local empty autouse override described above.

存量数据处置：no Schema, SQL, journal, approval, Task, artifact, snapshot or workspace
migration. Preserve exact Requirement identity, failed evidence and retained files.
This performance repair neither approves nor restarts a delivery. Deploy or revert only
after current workers are idle; continue the original Requirement through its existing
public exact action. Rollback restores nested inspection cost and preserves stored bytes.
Fixture counts do not predict full production latency or prove absence of memory leaks.
