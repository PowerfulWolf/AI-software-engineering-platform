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

## 2026-11-02 settlement milestone, not a release

The read-only claim observer is published on the working branch at `beab94cd`.
The **unwired** typed route-transition settlement and MySQL Task/queue atomic
fence are published at `6c4ee494`; exact child/parent checkpoint binding is at
`ef966628`. A `route-transition-settlement` v1 record is sealed before SQL
consumption. It binds Task revision/history, unique expired claim and queue
history, latest `preserve_draft` baseline, full current inventory and capture,
original child `BLOCKED` checkpoint and parent joint checkpoint. It cannot
resume the old frozen CLI selection or invent a sixth Run, Context or result.
The low-level queue method closes only the sole orphan retry and appends one
`IMPLEMENTING → BLOCKED` Task event under the queue and Task fences. Its replay
requires the exact sealed record and historical rows.

The actual K1 child checkpoint is `BLOCKED` while its recorded `task_status`
is **IMPLEMENTING** at Task revision 5. Its digest is
`83db2f2c4dfd87a84a61e4e2f09ea83e9f4094bc7e48969a32769acc75de7673`;
the parent joint checkpoint digest is
`d00be9d883a6db1bb20bc71e5d8648d36149288460a165da0aaccf2ca6cde7e3`.
Production read-only probes rechecked both, the ended claim, latest baseline
`2fc6da9af728233e71ac67f1b841a70bc08ba969fc4474a4d5c03557b8acb793`,
current inventory `7a8aa99f42f7ceca5c2788c3d1296b15dbc4b92d39c77b50a0421ce6bb8c2385`
and 13 captured file paths. An explicit capture base of `e09c41e5` yields
capture SHA `d646bf2b2b944f694c76768fdf23759f98b6687917369039c77a12df201f22c8`;
the earlier Plan capture is based on `20ee8ac6` and must not be compared by
SHA to this current capture.

The Task has five StateEvents; its only accepted Coder progress is attempt 1,
Run `run_28fc1e87daaa4068972af1f237d3908e`, Context
`ctx_90379bb8d0e9247096f47c1817b010609f1683c45dbe757b53059dcc24a66d02`
at source `20ee8ac6`. There is no sixth Run or Context. A future source
variant may cite this **historical** Context only with explicit lineage; it
must never call it a failed sixth invocation.

Isolated MySQL tests for atomic rollback/commit/replay, route config tests,
Schema equality/validation, Ruff and Mypy pass. No production Task, WorkItem,
checkpoint or draft was changed. Do **not** call the settlement service on K1
yet: the special terminal source reader, same-Requirement RecoveryPlan,
independent approval and public Continue/QA/Review path are still missing.
The ordinary terminal reader cannot consume the stale child checkpoint or
invent a final Coder route. Finish those gates and a full public fixture first;
then publish under controlled restart, recheck current facts and perform the
one-time production settlement through the public interface.
