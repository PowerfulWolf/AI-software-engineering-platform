# Root integration and deployment gate

Integrated owned-session stop/finalization, bounded dynamic credential source provenance,
same-base completed-output rescue and exact recovery UI, then the narrow Darwin disappearing
PID recheck. All integrations retain original task/role/approval boundaries.

## Incremental verification on main

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/manager/test_production_execution_baseline.py \
  -k completed_output_same_base_pause_resume --tb=short

PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/execution/test_owned_session_stop.py \
  tests/execution/test_owned_session_inspection.py \
  tests/execution/test_owned_record_finalization.py \
  tests/contracts/test_owned_session_stop_schema.py --tb=short
```

- Public serial test-scoped MySQL fixture: **1 passed, 10 deselected in 35.73s**.
  The public PROPOSE → approved PAUSE → explicit RESUME completed independent Coder,
  QA and Reviewer with one candidate revision, without bypassing native verdicts.
- Owned session/inspection/finalization/Schema: **64 passed in 11.70s**.
- Scoped Ruff check/format and cumulative `git diff --check`: pass.
- Earlier integrated gates: 34 Schema/rescue tests, 65 source/finalization tests and
  97 DOM tests passed; scoped strict mypy passed for 36 changed files. The isolated
  narrow fix additionally passed strict mypy for its two code/test files.
- Independent inspection review found no blocking issue. No full suite was run.

The first combined public fixture failed after the QA outcome was saved and before Reviewer
started; only the exception class survived in its durable facts. A diagnostic replay passed.
The new errno 0/ENOENT seam tests reproduced a specific short-birth-query defect, but do not
prove that defect was the original fixture's unique cause. Keep this limit in the handoff.

## 存量数据处置

Production K1 remains on the same Requirement/Task/branch. Its run8 actual local-limit stop,
unknown outcome and complete retained draft have not been rewritten. Read-only checks found
no run8 SID members, leader or observed tool, and no active claim. The old service was
controlled-stopped successfully before integration. No direct production SQL writes or
historical proof upgrades were made.

After publishing the fixes, start the new version and fast-forward the clean registered
repository. For run8 use the public `PROPOSE_EXECUTION_BASELINE` with `purpose=source_rebind`,
the exact fresh checkpoint/current work identity and latest full main SHA. The trusted collector
may seal a current interruption receipt from real start/stop and complete legal inventory;
it must leave the old unknown outcome unchanged. Review the complete plan and native-rule delta,
approve exact `EXECUTE_EXECUTION_BASELINE` with `continuation_mode=pause`, reverify the latest
binding and retained scene, then submit the separately bound `RESUME_EXECUTION_BASELINE`.
Do not use completed-output rescue for the typed run8 TIMEOUT, refund work, replay old approval
hashes, reset the Task, or create a replacement Requirement.

Fixture success is not K1 delivery. Production still requires a candidate, independent same-SHA
QA PASS, Reviewer APPROVE and complete Handoff.

## Risks and rollback

OS permission failures, incomplete surveys, observed birth escape and missing durable saves
remain unknown and block continuation. Owned-session proof does not contain an unobserved
`setsid()` escape. Historical stops keep their original leader/group scope.

Rollback only at a verified idle controlled-stop boundary. Preserve all saved operations,
plans, bindings, receipts, workspaces and failures. Any reader used after new optional proof or
baseline fields are published must continue to support those fields and canonical digests;
never strip or rewrite them to make an older reader accept the records.
