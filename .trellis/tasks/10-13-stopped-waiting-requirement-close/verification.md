# Verification facts

Workspace: managed isolated `k1-cancel-wait`; primary checkout unchanged. No commit, merge,
production data write, role verdict or model invocation was performed by this implementation.

- Before implementation, all 18 initial waiting-close contracts failed with the reproduced
  `Requirement can only be closed while blocked` gate.
- Final focused Python suite: 182 passed, 1 skipped in 134.43 seconds. Commands:

```text
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/manager/test_baseline_waiting_cancellation.py tests/manager/test_waiting_requirement_close.py tests/manager/test_requirement_cancellation.py tests/manager/test_requirement_deletion.py tests/manager/test_requirement_retirement.py tests/work_queue/test_requirement_queue_cancellation.py tests/web_console/test_manager.py --tb=short
node --test tests/team_view/waiting-requirement-close.test.cjs tests/team_view/ui.test.cjs tests/team_view/operation-progress.test.cjs
ruff check src/ai_software_engineer/multi_directory/{cancellation,deletion,service}.py tests/manager/{test_baseline_waiting_cancellation,test_waiting_requirement_close,test_requirement_cancellation,test_requirement_deletion}.py
ruff format --check <same seven Python files>
mypy --follow-imports=silent --cache-dir /tmp/k1-cancel-wait-mypy <same seven Python files>
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

Node suite: 33 passed. Ruff check/format and strict changed-file mypy passed. The MySQL tests
used the inherited isolated `127.0.0.1:3307/ai_software_engineer_test` DB, guarded and reset by
`tests/conftest.py`; no new container or persisted test resource was created. Real MySQL waiting-close cases
passed with Task state revision 2; crash recovery after the Task event resumes without
rewriting the receipt or duplicating state/queue events. The one skipped case deliberately
omits the same-item source overlay on a reserved successor; that successor instead has its
own immutable current-source step boundary.

Default transitive mypy additionally finds five pre-existing `PlanningBackend` /
`IntegrationRecoveryBackend` missing `verify_unstarted_design_rejection` errors in
`tests/manager/test_joint_planner_feedback.py`. Those unrelated fixtures are unchanged;
strict explicit-file checking above reports zero errors.

Rebound waiting source correction: real `consume_baseline` fixtures cover both same-item source
overlays and reserved successor identities. Waiting source is checked against fresh typed queue
step facts, and the new cancellation event uses that source while preserving old event bytes.
Both baseline pause and real release → Dispatcher claim → owner-fenced
`ENVIRONMENT_UNAVAILABLE` wait are covered, including a wait disposition without a baseline
ID. Each positive baseline fixture calls `validate_pre_candidate_sources` over its terminal
history with the real binding epoch.
Missing same-item overlay, missing immutable step, source drift before/after the receipt and
source drift in the mutation fence reject; no new receipt field or resolver is introduced.

Risks/limits: the generic CLOSED detail
still offers restart, but the service explicitly refuses restart after a CLOSE cancellation
and explains that a new Requirement is required; ordinary BLOCKED close/restart is unchanged.
Deletion preserves immutable audit and dirty code, and only withdraws execution authority.

Existing-data procedure and rollback are in `prd.md`, `requirement-deletion.md` and the team
console user guide. Keep the original failed CLOSE Operation; submit a new formal exact CLOSE
at idle, then reread and DELETE the new CLOSED checkpoint. No production SQL migration exists.
