# Continuing ASE-owned delivery, 2026-09-26

## Latest correction

Correction: the prior `MallocNanoZone=0` causal claim was premature and is withdrawn. Subsequent
same-app/environment A/B checks all failed, and CGSessionCopyCurrentDictionary independently showed
`CGSSessionScreenIsLocked=1`. The desktop is an unmet UI prerequisite. The user has been asked to
unlock it; do not bypass locking or collect credentials. Three earlier passing fixture runs remain
historical observations, not proof of the allocator hypothesis or a currently passing GUI gate.

Added fail-closed `--session-check` before candidate launch and checks before every driver action
and press. Locked desktop becomes a durable `NATIVE_UI_SESSION_LOCKED` receipt and an explicit
Manager unlock instruction, not a business verdict. Removed the unsupported allocator override;
keep actual AXWindow and strict checkbox 0→1 assertions. Three new preflight tests failed before the
fix (candidate launched without a usable desktop), then passed; the real host probe returns LOCKED.

Recovery test PTY 94133 completed: **31 passed in 706.61 s**. Expanded offline slice completed:
**163 passed, 3 opt-in skipped**. New UI receipt blocker test confirms durable BLOCKED and no repeat
driver call; optional UI receipt/schemas/Console facts tested. Current Console PID 68431 was started
before the final session-preflight changes: restart only after active Coder Operation completes.

## Live operation

- Coder prerequisite repair `ab419bfd34b16ba4ce105891b84af67c978652a57c5b8212bae3c67476d9103f`
  timed out (1800 s), retained 7 files, produced no candidate. Operation
  `operation_e453962519aec0beeea852d39e1d5b8c` SUCCEEDED as an operation, parent remains BLOCKED.
- Parent checkpoint `5f74049b8efc17dbec396eb5e1cf51d5f99d0c254cb7f0936ac2681f3ecf0c03`.
- Normal recovery proposal `operation_42c217aa1a944c3b544a4b1d7b5e416d` produced exact plan
  `a3bab307e33693507b2bfa542a32bc40a85918536326c12112de032dcf0a383d`.
- Reviewed 7-file capture, unchanged approved paths, no credentials/network/merge grant, current
  business main base `6d05fef305a6bcf225b526a3512c60e2679dbffe`. Approved through normal Console API.
- Active approval/execution `operation_2391e67108ef553a8c6d881e93346a7f`, new Task
  `task_recovery_a3bab307e33693507b2bfa542a32bc40`. Its own Coder is now active; do not restart Console.
- Console PID 68431 / PTY 93738. It was restarted only with no RUNNING/QUEUED operations.

## Additional platform repairs

- Legacy inconclusive-remediation fixture now manufactures only its historical admission with a
  scoped test monkeypatch, after proving the new guard rejects unapproved admission. Production
  policy stays strict and legacy admitted-Coder recovery is still covered.
- Installing Xcode exposed a fake-agent integration test accidentally discovering a real executor.
  Its capability detector is explicitly fake now; no production enforcement was weakened.
- A new MySQL/Git crash test exits after approved repair dispatch, reopens Host and verifies ordinary
  Coder → QA → Reviewer completion. 4 focused integration checks passed; later 3 legacy/new repair
  checks also passed. Original BLOCKED facts are preserved.
- Recovery previously retained edits/scope but lost the explicit repair objective. New
  `preserved_prerequisite_context` reopens the exact failed manifest, checks source Task/Coder,
  untruncated required source, repair proposal/authorization and exact redacted content. The real
  saved recovery plan readback found exactly one approved repair source. Tests reject truncation and
  substituted objective. No production records were rewritten.

## Native GUI capability (not approved for business execution)

- New `manager/native_ui.py`, trusted `native_ui_driver.swift`, optional candidate-plan capability
  and receipt fields, Console exact scenario proposal. Build keeps existing Codex sandbox; native
  mock app uses a separate versioned Seatbelt profile with network/source-write/user-home/Keychain/
  AppleEvents/unrelated-process restrictions. Driver targets only exact child PID/titled windows;
  never application/system menus. Press is not retried. Old omitted optional fields retain hashes.
- AXIsProcessTrusted host probe true. Existing Codex build sandbox denies GUI AX services; standalone
  native profile probe read checkbox and toggled it, and isolation fixture verified home/sibling read,
  outside write, network and other-process denial while scratch write succeeds.
- IMPORTANT: actual `run_native_ui` fixture is intermittent and often returns WINDOW_UNAVAILABLE.
  Do not call it verified or approve a business UI plan yet. Tests temporarily allowed this typed
  block, but that weakening was removed: current real test strictly requires both actual snapshots
  and checkbox 0→1. Investigating exact runner vs standalone probe difference. 2 s initial delay is
  insufficient by itself. Driver has bounded AXWindows error/count diagnostics now.
- Experiments ruled out mismatched child PID, compiler sandbox and driver TMPDIR/environment as
  sole cause. Standalone launch+driver outside helper succeeded 3/3; actual helper failed 3/3.
  No business GUI has been run. All experiments used platform-only AppKit fixtures.
- New spec `.trellis/spec/core/native-ui-verification.md`; update it after root cause is confirmed.

## Checks / outstanding

- 72 offline regressions passed, 3 opt-in tests skipped; 13-file strict mypy passed; Ruff/diff passed
  before latest diagnostic/recovery-context edits. New recovery-context code strict mypy passed.
- `tests/recovery/test_prerequisite_repair.py`, `test_execution.py`, `test_task_record.py`,
  `test_remediation_context.py`, `test_reapply.py` was still running in PTY 94133 (no concurrent MySQL
  suites). Read final result; do not claim it passed yet.
- GUI test session 46313 tests latest AX diagnostics; inspect result. Regenerate schemas after latest
  optional diagnostic field before final checks (`generate-verification-schema.py`,
  `generate-repair-schemas.py`).
- Need exact UI proposal/receipt/restart/failure tests, deterministic real GUI pass, then fresh
  candidate-bound approval, independent QA/Reviewer and original parent DONE. No merge/deploy.

## Boundaries

User delegated normal Manager gate review within this delivery. Codex edits platform only. Preserve
the old operator-authored business draft without using it. No direct Task/verdict/DB modifications,
no broad permissions, no test-result substitution for independent business QA.
