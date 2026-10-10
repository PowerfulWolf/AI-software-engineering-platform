# Verification

## Red signal

Before implementing the helper, the actual three filesystem projections ran against a real
temporary Git baseline plan, exact operator decision, start, binding and interruption receipt:

```text
.venv/bin/pytest -q tests/team_view/test_baseline_snapshot.py
FAILED test_three_actual_projections_validate_the_complete_binding_prefix_once
Expected one exact root/task call; actual list contained two additional identical calls.
1 failed in 6.77s
```

An earlier fixture-only run rejected a noncanonical repository ID; that was corrected before the
above red signal. The final test compares standalone three-call output with explicit shared
one-call output and checks all sealed sidecar JSON bytes remain unchanged.

## Incremental checks

```text
.venv/bin/pytest -q tests/team_view/test_baseline_snapshot.py \
  tests/team_view/test_task_read_snapshot.py tests/team_view/test_engineering_history.py \
  tests/team_view/test_continuation_history.py -m 'not mysql'
45 passed in 79.88s
```

The new cases cover actual `_TaskReadSnapshot -> _read_task_details` wiring to all three real
filesystem projections with a narrow read-only SQL adapter; exact root/task isolation; writer
rejection before cached reuse; finite empty prefix and next-snapshot append; historical plan,
authority, complete capture and symlink rejection; failed initial read not registered; actual HTTP
success/failure releasing the snapshot helper via weak references. Existing complete histories,
Task intent/scope/policy checks and standalone readers remain covered.

Ruff check/format, strict Mypy and `git diff --check` are run only for the four owned product files,
new test file and task probe. No full suite or production write was run.

Final results: **Ruff passed; 6 files already formatted; strict Mypy success for 6 source files;
`git diff --check` passed.** The shared working tree contains other agents' changes; this task did
not edit or revert them. `rg BaselineBindingSnapshot` confirms product imports/calls exist only in
the allowed `team_view` read modules, not writers or execution services.

## Real bounded comparison

Run these commands sequentially in fresh processes:

```text
.venv/bin/python .trellis/tasks/10-10-baseline-read-snapshot/read_probe.py \
  --config /Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json \
  --project project_ai-project_034252eb3595 --revision 267da45
.venv/bin/python .trellis/tasks/10-10-baseline-read-snapshot/read_probe.py \
  --config /Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json \
  --project project_ai-project_034252eb3595
```

Each has a 25-second process alarm. The probe only constructs `ProductionTeamReader`, existing
read-only stores and the original `READ ONLY` SQL transaction. Its SQL guard allows only SELECT,
the original repeatable-read setting and read-only START. No Host, schema initialization,
operation, claim, approval, provider, restart or source write occurs; only numeric facts and hashes
are printed.

| Observation | Before `267da45` | Working tree |
| --- | ---: | ---: |
| Snapshot seconds | 6.7796 | 5.2838 |
| Complete bindings calls / seconds | 3 / 3.1226 | 2 / 1.5624 |
| Plan calls | 20 | 12 |
| Start calls | 8 | 4 |
| Required context calls | 8 | 4 |
| SQL calls / seconds | 202 / 0.3169 | 202 / 0.3128 |
| Wire seconds | 0.0017 | 0.0017 |
| Render seconds | 0.0043 | 0.0044 |
| Requests / Tasks | 2 / 25 | 2 / 25 |
| Response bytes | 2,023,014 | 2,023,014 |

Sealed selected Project journal/baseline inventory is identical in both rounds and before/after
each round: **263 records /293,873,960 bytes**, SHA-256
`2a198ca765d9753b211078466a4a741f31c627b7887cca24f9747a4c41d3247d`.
Wire SHA excluding top-level `as_of` is identical:
`0af017ff7160a6f285052e6c9f3788838bd9d54585989db0f19ad6eb16af024e`.

Exact root/task keys are hashed, never printed as source content:

```text
60b8bbdec7da491bbd8096d91bd510f7af16f0985f60e5eb005a64e08a2d0a3d: 2 -> 1
86f23af4b75f28036c5ed47560ea481dfc283b3d4b0f180fc7c7e53e88dccf3d: 1 -> 1
```

Thus the earlier aggregate three-call measurement spans two identities, rather than proving
three repeated checks of one Task. Actual production reduction is **3 -> 2**; the controlled
same-Task three-caller regression proves **3 -> 1**. This measured improvement is input-specific,
and does not establish a continuous-hour read or gate leak. Current successful public reads
already refuted that inference. The service has not been restarted or hot-patched by this task.

## Existing facts and rollback

No SQL/schema/Requirement/Task/approval/journal/workspace migration is needed; all source hashes
and original approvals remain intact. Once idle, controlled service loading activates the read
optimization and the same Project can be refreshed. Rollback only the helper and three read-side
wiring paths; this restores repeated full validation without altering any durable fact or role
execution requirement. Independent review and commit are owned by the root agent.


Independent read-only review found no blocking issue in the helper, three caller checks or
per-HTTP lifecycle. No repeated performance probe was needed; exact fresh authorization remains
outside this snapshot helper and HTTP success/failure lifetime tests retain worker ownership.
