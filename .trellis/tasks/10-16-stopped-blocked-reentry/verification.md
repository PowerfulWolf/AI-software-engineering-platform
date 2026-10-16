# Verification and original K1 treatment — in progress

## Reproduction

Two new regressions fail against the original implementation: the public real-native/MySQL
blocked-raw-owned fixture cannot enter an engineering wait after Continue, and the real
service-to-next-Coder same-base stopped rescue loses its accepted continuation checkpoint.
The latter failure is `continuation_checkpoint_id=None`, not an absent original artifact.
The fixture uses a real child/stop and an expired original claim; it does not fabricate a stop.

Both original RED cases then pass (2 passed in50.49s), including the public blocked fixture
through safe wait, exact PAUSE/RESUME and independent QA/Review DONE, and the same-base
producer-to-real-next-request progress check. The strengthened progress case retains completed
steps01/02, selects03 and leaves04 deferred; it does not repeat completed steps.

Four public re-entry negatives initially pass (4 passed in19.34s): late raw artifact, sealed model route,
real Dispatcher successor claim with a non-increasing claim clock, and current UNKNOWN session.
Each refuses without a new delivery checkpoint, model call or Task change. A fifth conservative
closed-successor/parent-edge case and an unexpired-original-lease case were then added.
The latter passes separately (1 passed in5.78s); all public cases have passed in the author's runs.

Independent reviewer service-to-runner/progress and baseline-history checks pass10 cases
in31.02s: new same-base stopped rescue preserves the accepted checkpoint/paths and completed
steps01/02, selects03, and does not revive historically retired progress. Existing source-changing
recovery still retires progress under both modes.

The fixed independent reviewer additionally runs the complete re-entry selection with real native
children and isolated MySQL: 7 passed, 2 deselected in71.87s. This includes the blocked positive
through exact rescue and six refusal cases: late artifact, late route, real later claim with a
non-increasing clock, CLOSED direct child, original unexpired lease and UNKNOWN current session.
It checks no repeated main Coder call, original Task/events/source/record bytes, and no new
checkpoint for refusal. The reviewer reports no blocking issue. Strict Mypy for all six changed
source files, Ruff/format for all nine changed Python files, and diff check pass independently.

The author's complete affected regression run passes68 tests in304.02s:

```text
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q --tb=short tests/manager/test_stopped_execution_delivery.py tests/manager/test_stopped_execution_rescue.py tests/manager/test_stopped_failure_retry.py tests/orchestration/test_baseline_history_inputs.py
```

The final unexpired-original-lease parameter was added after that run and separately passes
1 test in5.78s. All final public parameters are also covered by the reviewer's seven-case
selection. The author additionally passes strict Mypy, Ruff/format and diff check for all
nine changed Python files. No isolated database test remains running.

The implementation shares the existing typed stopped-execution reader with baseline collection,
adds a narrow trusted Task-lock re-entry scope and preserves compatible progress only when a
new same-base STOPPED_EXECUTION_RESCUE binding is produced. General blocked retry, old
retirement records, immutable invocation history and source-changing recovery stay unchanged.

## Required checks before deployment

Public original-Task Continue/reclaim/guard/wait then exact PAUSE/RESUME must pass with no
repeated main Coder invocation. Genuine read-only knowledge preparation under a fresh claim
remains a separate allowed fact. Current-live/later claim, route/outcome/output/receipt/raw
artifact, stopped-proof and scope drift must refuse. Verify actual downstream request paths,
accepted completed steps and independent same-candidate QA/Review in the offline fixture.
Ruff/format, strict Mypy and fixed independent read-only review remain required.

## 存量数据处置

Target only original Requirement `delivery_multi_bb78e2316afca47d005384542f685174535b69db`,
Task `task_recovery_622f711324450abfffedc2a8d696e2de` and stopped Run6
`run_d244856b1962415b8e386adac7bfbe73`. Frozen execution source stays
`774e0a6fcc920d9a6ce3738e80b9cc43045be7eb`. Original195 immutable records and complete
draft remain available; accepted progress covers steps01/02. No production SQL, original
stop/outcome/verdict, base, Task terminal reset or business checkout edit is authorized by
this maintenance task.

After checks and controlled deployment, obtain fresh public Requirement/Task/queue facts.
Continue uses Dispatcher expiry/reclaim and a fresh guarded claim; it must enter the existing
engineering wait rather than repeat the main Coder. Prepare a fresh stopped-execution rescue,
review its exact inventory and same-base proof, record the user's delegated engineering
approval for PAUSE, then independently submit latest-bound RESUME. Check new claim/context,
complete retained draft, accepted steps01/02 and honest unknown history before further delivery.
Original PID5104 stopped through the existing controlled script. Exact request
`console_shutdown_29e41ef9ed5679180bdb0ec9d48be8de` and its instance/result match;
READY was published at2026-10-16T06:34:12.510598Z, 1.467602 seconds after the request.
Independent host inspection confirms original PID5104 and supervisor5181 absent, both
pidfiles absent and all195 original immutable files unchanged. Audit
`/tmp/ase-k1-controlled-stop-independent-audit-20261016-0647.json` SHA
ff781cbcaf7fbc2eda95d7ab6ef4f45d503a52c7f9107ed93270c698e48f13fa records these observations.
No fault retirement, inspection successor or maintenance-completion exception was needed.
At the implementation commit, deployment and public original-K1 re-entry were pending.
The actual observations are recorded below.

## Actual deployment and re-entry

Maintenance229eabd (includingf3be38e) was independently reviewed, merged/pushed to main and
started under new instance console_instance_69a6aab47708df27e2aa5547fffb9311, PID17458.
The public Continue operation_04b806b5df43944929dcea7567bca9c7 succeeded at07:00:16.897601Z:
old claim EXPIRED, fresh guarded claim RELEASED, WorkItem EXECUTION_UNCERTAIN wait. Original
Task/revision/attempt/source and all existing main starts/outcomes remain unchanged; there was
no repeated main Coder call. The fresh claim completed real read-only knowledge preparation.

The subsequent rescue proposal was rejected by an independent historical incoming-admission
compatibility defect, before execution or a new reservation. Follow maintenance task
10-16-replay-guarded-admission for its exact independent evidence and remaining treatment.
This re-entry task's deployed behavior is verified; production K1 delivery remains unfinished.

## Rollback

Controlled pause/stop before reverting code. Retain all appended checkpoints, queue lifecycle,
recovery binding/readers and approvals. Do not delete UNKNOWN history or restore stale queue
rows to make old code accept them. A candidate still requires real independent QA and Review;
offline regression results do not constitute production K1 verdicts.
