# Implementation sequence

1. Add a red test at the baseline public resume boundary for CLI-to-Responses drift; implement the pre-consumption guard.
2. Add an exact K1-shaped fake/SQL fixture for expired no-invocation claim, retained baseline and dirty draft. First prove no settlement or successor currently exists.
3. Add a typed settlement with queue/Task fence and immutable record. Verify replay and all negative cases.
4. Add dedicated RecoverySource variant, full current-facts reader and Schema synchronization; route public Continue to exact proposal and existing approval/new Task pipeline.
5. Run public fixture through new Responses Coder, QA and Review. Recheck production K1 facts before any live settlement, publish under controlled pause, approve via the public interface, then follow through to accepted handoff.

## 2026-11-02 read-only K1 evidence

The guarded production service is running from release commit `fb2bab2a`; the
registered K1 checkout is clean at the same `main` revision. A post-restart
read-only SQL snapshot still shows old Task revision 5, `IMPLEMENTING`, attempt
6; its sixth WorkItem remains `RETRY_SCHEDULED` at dispatch sequence 3, its
unique claim is `EXPIRED`, and the latest queue event is `LEASE_EXPIRED` sequence
908. No settlement or seventh claim was created by restart.

`/private/tmp/k1_claim_probe.py` used the production queue's
`original_claim_record()` read port. It returned `immutable_snapshot=True`,
the exact sixth WorkItem, original dispatch sequence 2 and original claim
expiry at 2026-11-02T08:46:52.258075Z. `/private/tmp/k1_no_start_probe.py`
then used `CapacityInputReader.require_claim_not_started()` with the exact
ended claim and `UninvokedClaimBoundary`; it returned
`NO_START_PROVED work_92cfc595361e54c5616693518f2572a8cd321b2bf98974e9b371fc9e207ea96a 2`.
These are read-only current observations, not a saved settlement or authority
to resume the old Task. A production settlement must repeat them under the
Task/SQL fence and bind the complete retained baseline and Git inventory.

Allowed paths for this engineering task are the exact manager, queue, recovery, web-console, Schema, tests and `.trellis/spec/core/` files identified by each milestone. No K1 ProductSpec, Design, Plan, old Task record, old dispatch or captured draft body is edited by this platform patch.
