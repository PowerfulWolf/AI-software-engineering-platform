# Verification — 2026-10-10

## Root cause and affected graph audit

`JointCheckpoint.model_json_schema()` and `StageWorkflowProof.model_json_schema()` each differed
from their published schema only in `$defs.DeliveryNextAction`. Both checkpoint graphs used the
Manager enum's short-name reference, but the legacy synchronization script flattened definitions
from independent models and overwrote the definition with TeamSnapshot's domain disposition enum.
The Manager generator itself produced the correct graph.

One read-only program enumerated every `schemas/*.schema.json`, selected definitions whose title
is `ProjectDeliveryCheckpoint` (also checking a root of that title), resolved the next-action
reference and compared its enum to the actual Manager enum. The only affected documents were:

- `requirement-checkpoint.schema.json` / `JointCheckpoint`.
- `knowledge-stage-workflow.schema.json` / `StageWorkflowProof`.

The second graph was caught by independent review and added with root's explicit authorization.
Both static files retain their existing JSON order and change only the enum's 8 incorrect values
to its own 11 correct values. No model/wire signature or persistent fact changed.

## RED evidence

- Initial requirement-focused regression: **14 failed / 1 passed**. Existing exact model parity
  failed; valid RUN_DELIVERY/REQUEST_HUMAN/NONE children were rejected; all 8 disposition-only
  actions were incorrectly accepted. The real Manager → legacy synchronization sequence in a
  temporary directory proved that the second script introduced the corruption.
- After extending regression coverage to the knowledge graph, before fixing it: **14 failed /
  2 passed**, including existing `tests/knowledge/test_schema_parity.py` for StageWorkflowProof.

## Fix and tests

The legacy script lists both graphs as exact standalone models, and its additive name-based pass
skips all standalone paths. This prevents an intermediate publication of a corrupt graph, while
retaining the script's final exact standalone semantics and existing handwritten legacy guards
in other documents. The final generation remains complete and repeatable.

Regression tests check each graph's exact reference enum, valid native child round-trip, rejection
of all disposition actions and an unknown value, actual script order, full graph parity and exact
bytes after repeat synchronization. The disposition graph keeps its own 8-value enum. Existing
schema parity tests remain unchanged and no differences are suppressed.

The touched older test fixture was adjusted to use explicit monkeypatch injection and typed helper
functions, removing existing strict-Mypy errors without changing its assertions or tested behavior.
The script's inner intent-model loop variable was renamed to avoid its existing conflicting type
inference. These changes affect test/development tooling only.

```text
.venv/bin/pytest -q tests/manager/test_joint_contracts.py \
  tests/contracts/test_local_legacy_rescue_schema.py \
  tests/domain/test_delivery_disposition.py tests/knowledge/test_schema_parity.py
91 passed, 2 dependency deprecation warnings in 4.55s

.venv/bin/ruff check scripts/sync-legacy-rescue-schemas.py tests/manager/test_joint_contracts.py
All checks passed

.venv/bin/ruff format --check scripts/sync-legacy-rescue-schemas.py tests/manager/test_joint_contracts.py
2 files already formatted

env MYPYPATH=src .venv/bin/mypy --follow-imports=silent \
  scripts/sync-legacy-rescue-schemas.py tests/manager/test_joint_contracts.py
Success: no issues found in 2 source files

git diff --check
passed
```

Only incremental tests ran. No full suite, production operation, approval, restart or delivery
resume was executed by this task.

## Independent review

`/root/coder_python_tooling_fix/joint_schema_review` completed read-only re-review. Its original
medium finding (knowledge graph omitted) is closed; no remaining/new finding was reported.

- Independently reran the original failing knowledge parity, script sequence/replay and both
  graphs' relevant positive/negative contracts: **16 passed / 53 deselected**.
- Copied all schemas into a temporary directory and ran the latest synchronization script:
  no semantic differences remained, and both graphs exactly matched their complete models.
- Checked **22 handwritten legacy guards**; all remained unchanged.
- Independent `git diff --check` passed. Reviewer changed no files or production facts.

## 存量数据处置与回滚

No database repair or journal migration is required. Runtime models and all immutable bytes/digests
are unchanged, so existing valid checkpoints/proofs validate with the corrected static contract.
Original requirements, workspaces, approval scope and failure/evidence history remain intact.
Root owns deployment and continuation of the original requirement through public platform commands.

Revert the two schemas, synchronization-script changes and related test/spec changes to roll back.
This restores the old validation defect but does not modify any existing facts or approvals.
