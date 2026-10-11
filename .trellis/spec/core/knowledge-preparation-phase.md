# Delivery execution knowledge preparation phase

## Scope / interface
This is a presentation-only read projection. It never permits a call, retry,
approval, role transition or verdict. RoleQueueView.execution_phase is an optional
Literal[KNOWLEDGE_PREPARATION, ROLE_EXECUTION, FINALIZING], excluded when None to
preserve nested legacy hashes. The read helper accepts trusted sidecar and scope
facts plus freshly validated current queued work, assignment and lease.

Signatures:
- read_claim_source(cursor, *, scope, item, lease, allocation_sha256) -> str | None
- read_execution_phase(*, scope, item, assignment, lease) -> ExecutionPhase | None
- resolve_step_overlays(original, records, *, baseline_sha256=None, latest=True)
  -> tuple[QueuedRoleStep, bool] is the existing writer algorithm extracted as a
  pure helper. It grants no queue or inherited-baseline authority.

## Contracts
Only RUNNING with a valid current lease may receive a phase. Saved knowledge
QueueClaim must match immutable work-item/task/repository/role/attempt/checkpoint/
dispatch/scopes, assignment, agent, lease and acquired time. Do not compare whole
objects: the saved item status is LEASED and lease expiry can have been renewed.
Current SQL owns liveness. Team/project/requirement/task/repository/source scope
must match; only the exact native lane and known Task-id legacy lane may be read.

Source comes from the exact hashed QueuedRoleStep and validated baseline overlays
before the current CLAIMED event, not Task.base_ref or a previous candidate SHA.
The existing queue event table has no sha256 column: validate its complete typed
row/payload, exact claim lease/item/dispatch/status/time and pre-claim rebound
ordering, then match rebound binding/plan/next-work/reservation to an independently
hashed BaselineQueueConsumption. Read at most 100 consumed baselines; duplicate
versions and invalid scopes reject. Unsupported inherited epochs stay neutral.
Reuse resolve_step_overlays; writer-only inherited authorization remains in
effective_step and is never invoked by this projection.

A knowledge invocation intent means knowledge preparation, even when its outcome
is already sealed. Main-role DeliveryInvocationStart for this current work/lease
takes precedence and means ROLE_EXECUTION. Its exact sealed outcome means
FINALIZING (saving/checking the local result), not QA/Review acceptance or success.
Missing old receipts remain a neutral unknown fine phase. Historical runs and
RUNNING Operations cannot establish a current role phase.

Neutral live claims use ROLE_WORK_CLAIMED / "已领取当前工作, 细分执行进度暂未上报".
They do not assert that the main role call has started. Validate knowledge outcomes
against their exact intent and re-read each embedded execution receipt by SHA;
an embedded receipt alone is insufficient.

All stores are read_only; missing stores never get initialized. Bounded listing,
bounded regular-file reads, ancestry/no-follow checks, model validation and digest
validation are required. Corrupt/unsafe records fail closed, never turn into an
apparently running main model. No cross-snapshot cache may retain this phase.
Each eligible scope lane permits at most 512 intent filenames, counted before
payload reads; unknown lanes are never scanned. Symlink ancestry, including a
dangling root, is unsafe rather than missing.

Task execution reason_code and Chinese reason/next action derive from the queue
phase on every projection recomputation. Requirement execution copies its active
child. Frontend Task, Requirement and activity presentation consume that same
execution text, keeping phase distinct from delivery stage and model completion.

## Validation matrix
| Input | Projection |
| --- | --- |
| Valid current claim + exact knowledge intent | KNOWLEDGE_PREPARATION |
| Knowledge outcome saved, main not started | KNOWLEDGE_PREPARATION |
| Exact main start, no outcome | ROLE_EXECUTION |
| Exact main outcome | FINALIZING |
| Renewed current expiry, immutable identity unchanged | Preserve phase |
| Approved pre-claim local source overlay | Match exact overlay source |
| Unsupported inherited source epoch | None, neutral live claim |
| Wrong claim/dispatch/attempt/source/scope, or no old receipts | None |
| Wait, expired lease, terminal role | No running phase |
| Corrupt hash/record, symlink, FIFO, oversize/overcount | Fail closed |
| Outcome embeds a receipt missing from its independent store | Fail closed |

## Tests / existing data / rollback
Independent read-helper fixtures cover positive, negative, precedence and unsafe
inputs with before/after file inventories proving zero writes. Task/Requirement
Python and DOM tests verify shared text; Schema tests verify exact parity and
legacy omitted/null field stability. Run incremental suites only. No SQL migration
or historical fact backfill is allowed. Roll back optional projection/presentation
while retaining new immutable receipts and the original audit history.
