# Stable Darwin identity and exact legacy continuity

## Reproduced contract defect

Darwin `kern.boottime` is an adjustable wall-clock value. The original stop proof encoded
seconds and microseconds into a string. Comparing that spelling after clock adjustment
rejected the same actual boot session before performing the original process checks.
New owned-session observations use canonical SHA-256 of `kern.bootsessionuuid`; the model,
wire shape and existing proof bytes do not change.

## Explicit interfaces

`RecordedBootContinuity.require_current(proof, observed_boot_identity)` is a private typed
read-side seam. `require_recorded_session_empty(proof, *, boot_continuity=None)` remains
strict by default. A mismatched legacy boot can use an explicitly composed verifier only;
the original leader occupancy, every observed original birth (including escaped SID),
complete SID double scan and final fresh boot check remain mandatory. The verifier runs
both before and after those scans and cannot grant a signal capability.

`ScopedNativeStopVerifier.require_knowledge(receipt, outcome, context_sha256)` reopens the
original intent/outcome envelopes, all independent execution records and the exact verified
Context body. The outer lane reader first validates every real claim, step, context and
frozen snapshot, then passes the receipt and full context SHA. The complete lane is still
validated; no historical claim is skipped. `require_stopped(stop, request)` instead reopens
that exact Run's original capture start and capture stop in the private continuation store.

`ProductionBackend.execution_baseline_service` alone installs this verifier in the baseline
collector. The collector forwards it to all three knowledge readers and to capture-stop
reconciliation. Direct callers, absent verifiers, unrecognized proofs and other recovery
entry points retain their existing strict stop checks. No request body selects a verifier,
anchor, allowed UUID, callback, proof family or bypass flag.

## Trust and complete ancestry

The supported producer is the existing v0.1 trusted local `codex_cli` Popen runner writing
independent receipts into the unique private sidecar. Model responses and task text cannot
write these stores. This bridge does not establish locality for imported/migrated/remote
execution records and adds no such import capability.

For each boundary read, reopen the current Task, then follow exact approved recovery records
toward the anchor. Validate `FileRecoveryStore.get_plan/get_authorization/get_task_record`,
Task intent, source scope/native delivery, retained joint parent, predecessor Task complete
hash and revision, terminal state, and time ordering. Reject cycles and paths exceeding
`MAX_INHERITED_REAPPLY_INPUTS`. Each ancestor's baseline store is opened at its own Task
path. `bindings_for_task` revalidates exact plan/start/authority/complete retained patch.
Only an ENGINEERING operator PAUSE binding of a valid `knowledge_isolation` proof supplies
a stable boot anchor. Proposal-only records supply none. The trust boundary is the exact
approved anchor; ancestry before that independently authorized anchor is not needed.

Anchor scope/team/project/repository/path/native and joint Requirement identities are exact.
All four stored surveys remain valid and idle. Current stable machine/session hashes and
current account must match. The anchor's completed observation precedes the original native
admission/capture start, which precedes its original proof observation. Original receipts,
proofs and authority references remain unchanged. The older isolation's UNKNOWN outcome is
never changed into a historical stop or no-start fact, and its execution authorization is
not reused or transferred.

## Conservative temporal rejection

Legacy Darwin boot and birth fields must parse as bounded positive seconds plus valid
microseconds. All observed births must be from Darwin, no earlier than the original
leader/admission, and no later than the original stop proof. Recorded boot may not postdate
the original admission or predate both trusted anchor/current boot timestamps. This final
lower bound is an extra fail-closed consistency restriction: a legitimate historical
whole-second clock drift can be rejected. It does not establish same-machine identity;
only the complete stable UUID/machine/account/producer/lineage conjunction does. No equality,
tolerance window, PID absence or service restart substitutes for that conjunction.

## Validation matrix

| Case | Required behavior |
| --- | --- |
| New valid canonical UUID | stable hash, unchanged proof model |
| Missing/denied/malformed UUID | reject without boottime fallback |
| Exact original local receipt, approved same-boot ancestor | original process checks still run |
| Proposal-only/missing authority/foreign scope/changed ancestor hash or revision | reject without writes |
| Changed original receipt/outcome/independent record/context/capture envelope | reject |
| Changed machine/session/account before or during scans | reject |
| Recycled leader PID, live original birth, occupied SID | reject |
| Legacy numeric/birth/time contradiction | reject, never seconds-only acceptance |
| No explicit bridge | retain strict mismatch rejection |

## Stock-data handling and rollback

No SQL migration or historical rewrite is required. Diagnose the exact original Task/native
and joint checkpoints, retained source, full draft inventory, original receipts and approved
anchor/recovery lineage. Install reviewed compatible readers at an idle controlled restart.
Re-propose the original same-base stopped-failure plan, record a correct exact current
ENGINEERING PAUSE, verify one ordinary-work successor and retained immutable history, then
issue separate latest-bound RESUME. Check a fresh claim/Run/Context and keep independent
candidate QA/Review gates. A diagnostic PASS alone grants no recovery authority.

If continuity cannot be demonstrated, preserve the current wait and all drafts/history.
Rollback only after controlled stop; keep readers compatible with already published new
UUID proofs. Never strip proof fields, refund budgets, rewrite failed operations or dispatch
an original ended claim. No Coder, QA or Reviewer policy is expanded.
