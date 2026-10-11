# Implementation and verification handoff

## Revision, ownership and scope

Implementation base: `60512345ebcb15986a93e1458ffec554e59a139d` in the separate detached
`/Users/zhangjunshuai/workspace/code/ase-recovery-contract-research` checkout. The implementation
author is `/root/recovery_read_cost/task_projection_reuse/sentinel_attack_review`; root owns
the independent review. The test-only child owns `test_completed_output_checkpoint.py`.
This document records implementation evidence; it is not a QA or Review verdict.

No commit, push, deployment, restart or model call was performed. The production main checkout,
runtime, sidecars, worktrees, cache and persistent facts were not modified. The one authorized
MySQL public test used the existing isolated test fixture and its database-name safety check;
no production configuration or DSN was read. Root separately owns stock-cache maintenance.

## Implemented contract

`CompletedCoderOutputUnavailableProof` binds the immutable original invocation outcome and
capture start/stop. It requires Coder FAILED / WORK_INTERRUPTED / nontransient / no artifact,
real native completed returncode 0, output present, and no interruption/provider cause. The
collector validates the historical claim, exact Requirement/dispatch scope, current queue
step/source, frozen permissions and durable records under the existing idle and Task fences,
then rechecks the actual original process group through `validate_capture_stop`.

`BaselineExecutionFacts.completed_output` and
`BaselineExecutionReservation.completed_output_sha256` are omitted when absent to preserve
historical wire bytes and digests. The separate `completed_output_unavailable` reservation
consumes a fresh ordinary-work attempt without a refund or transient failure. Existing queue
consumption needs no new branch or state-machine change. The existing different-target
SOURCE_REBIND and exact PROPOSE / approval / PAUSE / explicit RESUME flow remain authoritative.

Proposal compares the original complete before inventory with the stable current complete
inventory, authorizes every changed path including ignored noncache files, and requires full
noncache draft/inherited-path coverage. The final Plan model also performs a pure body versus
inventory kind/SHA/mode/size/deletion and coverage check. It does not read the current filesystem
while decoding historical plans. Existing secret, symlink, index, body-size, protected-path and
current-inventory checks remain active.

Root's independent review found two additional gaps, both addressed before final handoff:

- `queue.accepted(task)` retains publication receipts after consumed rejected-output recovery.
  Exclude only an exact ID in `rejected_output_artifact_ids(task)` belonging to different work;
  never exclude current-work, unconsumed or ancestor IDs, and never delete the raw history.
- Validating only at proposal time left final Plan wire decoding without capture fingerprints.
  `ExecutionBaselinePlan.validate_plan()` now invokes the pure capture/inventory validator.

Canonical Schema guards are in `scripts/sync-legacy-rescue-schemas.py`. Both standalone
writeback loops apply them, including the final loop that previously erased standalone gates.
Only the baseline plan, queue consumption, console operation and new proof Schema changes are
included; unrelated generator rewrites were restored to the base revision.

## Test evidence

All commands run from the independent checkout. `PYTHONPATH` selected its source; the main
checkout's existing virtualenv supplied installed tools read-only. No credentials are recorded.

```sh
PYTHONPATH=/Users/zhangjunshuai/workspace/code/ase-recovery-contract-research/src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest tests/manager/test_production_execution_baseline.py \
  -k completed_output_unavailable_pause_resume -q --tb=short
```

The first red run used the actual public Host callsite. A real test-owned process wrote a legal
draft, temporary last message and 22 MB synthetic cache, then exited 0. Final inventory rejected
before parsing; the test asserted the immutable FAILED/noartifact outcome and real completed
stop. After separate isolated-fixture cache maintenance, public proposal failed at the old
reservation gate. No successful artifact, timeout/provider cause, refund or cache diagnosis was
invented. The actual existing wait classification was TRANSIENT_INFRA and is recorded as such.

First implementation green: **1 passed, 9 deselected in 64.35s**. Final run after both root
findings above: **1 passed, 9 deselected in 53.26s**. The public case covers exact approval,
PAUSE/replay/latest-bound RESUME, fresh normal-work Coder claim, then independent QA/Review,
with unchanged original failure, Requirement/Task/branch identity and audit history.

```sh
PYTHONPATH=/Users/zhangjunshuai/workspace/code/ase-recovery-contract-research/src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q --tb=short \
  tests/manager/test_execution_baseline.py \
  tests/manager/test_baseline_wait_fact_collection.py \
  tests/manager/test_execution_baseline_reservation.py \
  tests/manager/test_execution_baseline_invocations.py \
  tests/manager/test_paused_baseline_service.py
```

Result: **38 passed in 112.13s**. These existing no-DB modules cover proposal/fact collection,
ordinary/transient reservation, immutable invocation lineage and paused baseline service.

```sh
PYTHONPATH=/Users/zhangjunshuai/workspace/code/ase-recovery-contract-research/src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q --tb=short tests/contracts/test_repair_schema_generation.py
```

A new red case proved the initial Schema allowed a forbidden retry_failure for the ordinary-work
cause. After the canonical guard fix and regeneration, **12 passed in 3.30s** on the final run.

The test-only child added 67 parametrized cases in
`tests/manager/test_completed_output_checkpoint.py`: proof/Schema constraints, original
digests, real fenced collector and live-process rejection, scope/claim/source/permissions,
exact retired-publication handling, ignored noncache and secret checks, full Plan fingerprints,
ordinary-work exhaustion/no-refund, and historical excluded-None wire/digest compatibility.
Initial run: **57 passed, 10 failed in 34.42s**. The failures were confined to invalid fixture
Context IDs and a legacy unnamed fixture Task rejected by normal baseline rules. Those ten
cases were repaired without changing production code or the other 57 cases' setup. Targeted
rerun: **10 passed, 57 deselected in 31.35s**. No MySQL or model call occurred in these cases.

Final Ruff, formatting, strict mypy and patch-whitespace results are recorded below after the
handoff artifact is finalized. Root's independent review result belongs in root's handoff.

## Existing data handling

No direct data repair is part of this patch. Original run7 FAILED/noartifact, completed stop,
output-present Boolean, attempts, leases, receipts and history remain immutable. Its output
bytes are unavailable and are not reconstructed. No cache-cause evidence is added.

After root completes the separately authorized exact cache preservation/removal audit and
loads compatible code at a controlled idle boundary, the authorized public path is:

1. Propose SOURCE_REBIND for the same nonterminal IMPLEMENTING Task and the different exact
   approved target source, preserving its complete legal draft.
2. Inspect the entire sealed plan, original proof, complete captures, inventory and normal-work
   reservation; resolve any scope, authorization, drift or budget failure without rewriting facts.
3. Obtain engineering approval for that exact plan ID/digest with PAUSE.
4. Explicitly RESUME the latest exact binding after its source/inventory checks.
5. Let the normal Supervisor obtain a new Coder claim, then independent QA and Review.

A terminal Task, incomplete/unauthorized draft, missing/unknown/live stop, accepted/adopted
publication or exhausted frozen normal-work budget remains ineligible. This patch does not
authorize a production proposal, approval, resume, DB write or cache removal by itself.

## Limits and rollback

The native-stop contract still proves leader reaped, real pipe EOF and absence of the original
PGID; session-wide descendant ownership is a separate researched future contract. No native
runner/session-stop change is included. No same-base rescue purpose or generic delivery
resolution capability is added. Schema semantic identity/digest equality remains enforced by
typed models and the fenced application service.

Before a decision is consumed, roll back by reversing only this scoped patch while retaining
all existing facts. After consumption, keep compatible readers/writers and prefer a forward
fix; never delete decisions, refund ordinary work, reset the Task or resurrect old queue work.
