# Bug Analysis: Standalone Reviewer-only Recovery

## 1. Root Cause Category

- **B — Cross-layer contract**: native `accepted_qa` requires a durable Task event. Standalone
  verification deliberately never rewrites that terminal Task; its all-role completion requires
  Review when QA passes. Sealed QA between those two boundaries was durable but not recoverable.
- **D — Test coverage gap**: native accepted-QA tests passed; no production propose/approve/execute/
  restart test asserted that standalone QA runs exactly once across Reviewer interruptions.
- **E — Implicit assumption**: absence of overall completion was treated as absence of usable role
  progress. Reviewer context construction can also fail before a Reviewer invocation exists.

## 2. Why Earlier Fixes Did Not Address This

The larger production context budget and authorized Reviewer route fallback solved context/provider
availability, not durable per-role recovery. Repeating an entire new QA/Reviewer plan could deliver
the requirement, but unnecessarily repeated QA. The first bounded proof required a Reviewer
admission; the added context-interruption test went red with `retained_qa is None`. Making that
reference optional, while binding an exact unique admitted QA report, covers the earlier boundary
without fabricating a Reviewer call or Task event.

## 3. Prevention Mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Typed contract | Distinct retained QA proof, never native accepted event/partial completion | DONE |
| P0 | Runtime validation | Exact sealed lineage, latest admitted attempt, controlled receipt, same UI scope | DONE |
| P0 | Negative coverage | Newer QA FAIL/Review verdict, missing approval, forged proof, candidate/report drift | DONE |
| P0 | Production-entry regression | Before/after admission and repeated interruptions, fresh composition | DONE |
| P0 | Real integration | Normal joint approval/restart → DONE, no repeated Coder/QA | DONE (4 cases) |
| P1 | Console | Reviewer-only scope, retained artifact/source plan/admission visible | DONE |
| P1 | Knowledge | New executable spec + index + existing native spec and docs cross-links | DONE |

## 4. Systematic Expansion

- Reviewed runner, admission/store, production facts, native completion/remediation adoption,
  Manager coordination and Console projection. They now use `plan.reused_qa` where either source
  is valid; native source derivation remains intentionally native-only.
- Independent Reviewer still receives required original plan/implementation/QA context and has a
  fresh role identity/approval. Controlled UI/build/test is new Reviewer evidence, not replayed QA.
- Do not generalize this into arbitrary artifact scanning or an all-role DAG. Each future recovery
  boundary must define its own exact durable proof and superseding-negative-result rule.
- No template/spec-guide mirror exists in this repo; new domain contract lives in core specs.

## 5. Knowledge Capture

- [x] `.trellis/spec/core/verification-role-recovery.md`: signatures, authority, matrix, tests.
- [x] Core index, native recovery spec and `docs/contracts.md` updated.
- [x] Existing PRD/design/task record refreshed with this user request and real business DONE.
- [x] Implementation remains directly in the current ASE workspace; no business source edits,
  production history changes, additional sub-agents, automatic commit/merge/push or task archive.

## Validation and Existing-data Handling

The first production-entry reproduction failed because the fresh plan ran `[QA, REVIEWER]` instead
of `[REVIEWER]`. The pre-admission extension also went red before its fix. Nine focused production
entry cases now pass, covering interrupted context/provider runs, successive interruptions,
newer uncompleted verdicts, and controlled per-role execution counts. Console tests cover both
native and standalone QA sources. Ruff, format and strict Mypy (238 modules), offline build pass.
Four real Git/isolated-MySQL joint recovery cases pass (138.48s). Final full suite/reload recorded
in the continuation log.

Final full offline suite: **1971 passed, 10 opt-in skipped, 101 MySQL deselected** (251.27s).
The ten skips are explicit local CLI/GUI/toolchain probes, not silently failed requirements;
two existing Starlette dependency deprecation warnings remain. Separate MySQL integration above
was executed, not skipped. Service loaded the fix after an idle graceful restart (PID43232/PTTY29107).
Commands: `.venv/bin/pytest -q -m 'not mysql'`; `.venv/bin/pytest -q tests/recovery/test_resume.py
-k test_joint_verification_approval_stays_current_and_completes_delivery`; `.venv/bin/ruff check
src tests`; `.venv/bin/ruff format --check src tests`; strict Mypy over source and changed tests;
`uv build --offline`; `git diff --check`.

Read-only compatibility validated all 39 production verification plans in 2.46s and the sealed
successful completion. No migration is required: historical plans omit the optional proof and
retain their hashes. For an unfinished eligible delivery, normal Continue proposes a fresh exact
Reviewer-only plan; approval runs only that role. Never replay the consumed old plan. The actual
business requirement is already DONE and must not be retriggered just to demonstrate this fix.

Rollback: undo only these Reviewer-recovery changes in the ASE workspace, preserving unrelated
dirty work and all append-only sidecar/DB facts, then reload while idle. Do not downgrade after
new-format plans have been issued without preserving a reader for `retained_qa`; no such live
plan has been issued in this task. Never reset business Task/verdict/approval state.
