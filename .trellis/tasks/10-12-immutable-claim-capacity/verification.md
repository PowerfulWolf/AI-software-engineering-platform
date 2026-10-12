# Validation and existing-data disposition

## Author incremental checks

All commands run with `PYTHONPATH=src` and the shared project `.venv/bin/python`, no full suite.

- `pytest tests/work_queue/test_original_claim_snapshot.py -q --tb=short`: 9 PASS / 2.71s,
  including real start, two owner-fenced renewals, unchanged raw original bytes, wait/release and
  seven corrupted new/legacy event cases. Contains one pure test, eight isolated MySQL tests.
- `pytest tests/manager/test_baseline_knowledge_parent_scope.py -q --tb=short`: first version
  2 PASS / 45.84s. Both genuine public joint Product approval/Design/Plan paths execute actual
  claim renewal before capacity, retain same Task/branch/budget, PAUSE/RESUME source update and
  reach independent QA/Review DONE. One retains new immutable event, one simulates legacy
  event absence while genuine RETURNED knowledge facts retain original raw SHA. Final revised
  provenance-conflict negative and complete rerun result are recorded below.
- `pytest tests/manager/test_public_verifier_capacity_resume.py
  tests/work_queue/test_knowledge_preparation_retry_mysql.py::test_real_local_limit_resolves_once_with_new_claim_and_same_task_source_and_progress
  tests/work_queue/test_worker_mysql.py::test_supervisor_claims_each_serial_role_including_retry_boundaries
  tests/work_queue/test_worker_mysql.py::test_worker_heartbeats_and_fails_closed_on_renewal_loss
  -q --tb=short`: 12 PASS / 48.14s. Original raw consumers, verifier stages, exact new claim,
  independent serial roles and real heartbeat-loss boundaries remain valid.
- Initial pure original-snapshot/legacy capacity checks: 9 PASS / 0.60s; original knowledge
  failure tests: 13 PASS. Latest reviewer runs 25 pure tests PASS with 9 MySQL deselected;
  counts overlap and are not accumulated as distinct runs.
- Strict mypy first nine changed source/test files PASS; reviewer latest ten files PASS.
  Final Ruff/format/type/diff results recorded below.

## Independent production SELECT-only replay

Reviewer script: `/tmp/ase-immutable-claim-readonly-replay-20261012.py`.
Uses actual trusted approved-parent/recovery ancestry, sealed original dispatch and Task,
original target preparation/profile recompilation and complete original permissions.
Does not construct Host or schema-initializing repository/queue objects, does not invoke a
provider, does not write SQL or stores, and does not fake held collector authority.

Exact production Task: `task_recovery_45588301d1b35b02f44762650b6195e4`.
Approved parent: `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`.

- Attempt 1: original failed knowledge proof unchanged, SHA
  `4ba569231a9ec3a5d42464ecbf4466ac2087c3e0bf788cdce2788160b941c92e`.
- Attempt 2: real main start/outcome, native capture/start/stop, claim/source/permissions/scope
  and policy PASS, native stop `local_execution_limit`; proof SHA
  `38dc3c0347526fa4dc16d6ca6772b581d6181c4562adfd291a3c05de89bac74a`.
- Attempt 3: receipt `7881…`, knowledge intent/assessment `383c8c…`/`7f4574…` each independently
  validate complete intent, outcome and observations. Both original snapshot raw SHA `5b9d734f…`
  equals capacity receipt's exact hash; current SQL raw `d7ed60b9…` differs only in lease expiry
  from 03:48:15 to 03:52:36. New provenance-aware legacy resolver returns the real original raw
  claim; identity + complete final Context + original complete permissions + all no-start scans
  PASS. Knowledge base Context and final capacity Context differ legitimately and each is
  fully validated. Replayed again after the new/legacy provenance guard was added: all PASS.

These are read-only diagnosis proofs, **not** execution, approval, real collector fence or
production public proposal results. Root owns service maintenance and real public proposal.

## Existing data and rollback

No production facts changed. Original requirement/Task/branch/worktree/draft, leases, events,
knowledge, capacity receipts, frozen approvals and retry counters remain. After loading the
compatible runtime, reprepare the exact source proposal in the original requirement, pass the
actual Task/SQL idle fences and workspace inventory validation, approve PAUSE, then explicitly
continue. Unknown or contradictory originals still refuse. Old verifier raw mismatches without
an independent complete snapshot do not gain a new exception. New immutable original events
must retain a compatible reader; rollback after publishing them should use a forward fix and
must never delete snapshots, history or approvals.

## Final release validation

- Latest `pytest tests/manager/test_baseline_knowledge_parent_scope.py
  tests/manager/test_capacity_legacy_claim_snapshot.py -q --tb=short`: **13 PASS / 47.21s**,
  two complete public new/legacy real-renewal delivery flows plus eleven pure exact legacy/raw
  snapshot cases, including new immutable authority refusing fallback, duplicate identical
  completed phases and different-expiry snapshot ambiguity.
- Changed ten Python source/test files: Ruff check PASS, Ruff format check PASS (10 formatted),
  strict mypy PASS (10 source files), `git diff --check` PASS.
- Independent final code/spec review PASS. Reviewer repeated production SELECT-only replay
  after the new/legacy provenance guard: all three original attempts still PASS. This remains
  read-only evidence; root will perform real production proposal/fence after controlled deployment.
- No full suite and no production provider/model/store/SQL mutation performed by this task.
