# Expired owner settlement for an unpublished rejected candidate

## Scope and failure mode

A stopped Coder may leave a sealed `SUCCEEDED` invocation whose implementation report
uses an unsupported artifact version. Its complete committed candidate is preserved, while
the original queue item can still be `RUNNING` and its last claim `ACTIVE` with an expired
lease. Expiry alone does not prove process termination. Ordinary `reclaim_expired` changes
the item and dispatch sequence and must not be used to make this original invocation fit a
candidate recovery proof. `idle_task_scope` continues to reject every `ACTIVE` claim.

This narrow service settles only the exact expired owner of an independently proven stopped,
unpublished unsupported-version candidate. It grants no retry, execution, acceptance or
approval. The later target-free `rejected_candidate_rescue` plan still requires an exact
engineering `PAUSE` decision, followed by a separate exact `RESUME` and a new real claim.

## Signatures and persisted facts

```python
class TaskProcessLockGuard(Protocol):
    inherited_fds: tuple[int, ...]
    def check_task_scope(self, task_id: str) -> None: ...

MySqlRoleQueue.settle_rejected_candidate_expired_owner(
    *, task_id: str, task_lock: TaskProcessLockGuard,
    collect_current: Callable[[], RejectedCandidateOutputProof],
    seal: Callable[[RejectedCandidateExpiredOwnerSettlement], str],
) -> bool

FileExecutionBaselineStore.put_expired_owner_settlement(
    record: RejectedCandidateExpiredOwnerSettlement,
) -> str  # exact immutable file URI
```

`RejectedCandidateExpiredOwnerSettlement` contains the complete original rejected-candidate
proof, exact Task revision, original claim digest, full current claim and digest, observed UTC
time and its own SHA-256. Its only resulting claim state is `EXPIRED`; `work_item_changed`
and `budget_refund` are literal false. The current claim may differ from the original claim
only in renewed `expires_at`. The locked current `lease_json` and indexed expiry must agree;
`original_claim()` returns immutable original bytes and must not be treated as a live expiry.

The namespace is the shared `EXPIRED_OWNER_NAMESPACE = "rejected-candidate-owner-stops"`
under the Task's existing `state/execution-baselines/<task_id>/` store. Do not expand the
generic namespace length limit. A private, atomically sealed record is read back before its
URI and digest enter the `REJECTED_CANDIDATE_OWNER_EXPIRED` queue event (within the existing
32-character event type column). An unused
observation can remain after a failed SQL commit; it is not evidence that settlement committed.

Physical deletion recognizes this exact typed namespace, canonical key and Task directory,
and separately checks the proof and current claim's formal Team/Project/Repository/Requirement
and Task identities. CLOSE retains the record. Unknown or foreign records fail closed.

## Authority and sequencing

The lock order is Task process lock → queue authority → Task row → active claim row.
`WorkerExecutionGuard.check_task_scope(task_id)` checks the private scope binding, exact Task,
live descriptor, original device/inode and visible private owned regular lock file. It does
not call or relax ordinary `check()`, which still requires a real Worker lease. A plain
nonempty descriptor tuple is not proof of the engineering Task lock. Nested, foreign, closed,
replaced, symlinked or public-mode lock identities reject.

Within the SQL fence, require exactly one unfinished original `RUNNING` Coder item and exactly
one active claim, belonging to that original invocation. Require the fresh trusted clock to
have reached its current expiry. Reopen the entire real unsupported-version `SUCCEEDED`
outcome, real complete owned-session stop, original capture/claim, clean exact candidate and
complete parent-to-candidate patch, current inventory and absence of publication. Check the
typed proof against the actual Task row, revision and immutable step. Independently reopen the
entire proof a second time before sealing. Check the clock again before sealing and before
SQL mutation; rollback on backward time or any changed proof/identity.

Only release that exact claim to `EXPIRED` and append the audit event in one transaction.
Retain the original item, dispatch sequence, invocation/outcome bytes, candidate HEAD/branch,
Task base/revision/events and all work/transient accounting. Then enter the unchanged strict
idle fence and collect the recovery plan normally. No model, Supervisor tick, Git mutation,
queue ready transition or budget reservation belongs to owner settlement.

## Validation matrix and executable checks

| Input | Required result |
| --- | --- |
| Exact stopped candidate, unique expired active owner | Seal proof, expire that owner once, retain original RUNNING item; normal idle fence can enter |
| Already no active owner | False, no new observation or scheduling mutation |
| Renewed lease now expired | Preserve full renewed lease in record; permit only expiry difference from original claim |
| Valid lease, multiple active claims or nonunique/non-RUNNING item | Reject with original owner and work untouched |
| Wrong Task lock, closed fd, inode/path replacement, symlink or public file mode | Reject without granting Worker authority |
| Missing stop, dirty/ignored extra bytes, original run publication, changed second read or backward clock | Reject; original bytes, owner and budgets stay intact |
| Record persisted but SQL failed | Retain unused observation; no committed queue event and original active owner remain |
| Exact settlement during physical DELETE | Include typed bytes; reject foreign scope/task directory or noncanonical storage key |

Relevant tests:

```text
tests/work_queue/test_engineering_task_lock.py
tests/manager/test_rejected_candidate_owner_records.py
tests/manager/test_rejected_candidate_baseline_production.py
tests/work_queue/test_rejected_candidate_baseline_mysql.py
tests/manager/test_rejected_candidate_admission_mysql.py
```

Run MySQL tests only against an identity-validated isolated test database, serially with other
MySQL suites. The production collector tests use actual Git, SQLite and a genuinely stopped
test-owned process; pure wire fixtures cannot establish real production stop or publication facts.
