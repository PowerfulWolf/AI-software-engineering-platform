# Verification and handoff

## Confirmed cause and correction

The approval was already durable. The old gap query returned only immutable questions, the
browser always constructed a new form, and the unchanged WAITING_HUMAN checkpoint still
contained its original instruction. This was a read-model/UI contract defect, not missing approval.
Approval and continuation remain separate explicit actions.

Implemented a shared verified gap/resolution projection, current-gap snapshot data, approved
answer/source rendering and resolution-aware cache invalidation. The old card-level continuation
omitted the expected checkpoint; it is removed in favor of the one existing guarded Requirement
action. Current knowledge waits cannot be overridden by preserved child checkpoints. Read-only
knowledge stores cannot mkdir or publish. Updated operator instructions and executable contracts.

## Automated evidence

- Ruff check and format check: passed (801 files formatted).
- Strict Mypy: passed (431 source files). Fixed three pre-existing enum-argument mismatches
  in the nearby model-diagnostics test fixture; no diagnostics runtime behavior changed.
- Focused knowledge/Console/Team/contracts suite: 349 passed before the final read-only-store
  hardening; subsequent focused query/diagnostics/schema suite: 28 passed.
- Final query/schema/read-only regressions: 3 passed.
- Node UI regressions: 35 passed, including failed Team reads, reopen after approval,
  same-checkpoint external approval and one exact-checkpoint continuation action.
- Offline source distribution and wheel build: passed.
- Full Python suite: 1607 passed, one pre-existing service-test environment assumption failed
  after 1318.97 seconds. That test expected an absent DSN but inherited one from the terminal.
  Its fixture now removes the inherited value to test file-only removal deterministically.
  All 24 service-script tests passed with the variable isolated; the formerly failing test
  also passed in the original environment after the fixture fix (7.35 seconds). No service
  runtime/configuration behavior was changed. The 22-minute full suite was not repeated.
- Only existing Starlette/httpx and anyio deprecation warnings observed in focused tests.

Red/green evidence: the new preserved-child projection test failed before its guard was added;
the UI detected two continuation controls and wrong IMPLEMENTING status, then passed after
consolidation. The missing-snapshot Operation regression failed with null.requests and passed
after a nullable lookup. No debug instrumentation or production-model replay was needed.

## Existing requirement, read-only validation

Console was idle (no QUEUED/RUNNING Operations) before reloading code with the existing service
configuration. The process was relaunched in a detached session so it survives the tool's process
group cleanup. Console now reports delivery_ready=true; the served app.js hash matches the checkout.

For Requirement `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006`, live GET now returns:

- gap `1f6681eefb26ed1a2a4ac59c8489d38dcab9c5814600a05cb81319f319c21593`, is_current=true;
- approved answer `A`, source `产品确认`;
- next action: `知识解答已批准，点击“继续交付”恢复原需求，无需重复解答。`;
- unchanged WAITING_HUMAN checkpoint SHA
  `f612518f2ce20e2de6348fd8668322e3ad07b753ad0156736142fba256ff84df`.

Checkpoint file SHA-256 remained `17b2910021704e5a01d32fed5385d960b4e2cf65c3acaa0eeb7ee5ec3a793a01`;
resolution index file SHA-256 remained `993ed447828533bb1a5bc56696d9ecaff2fa9845de24c32b884399ef36ff1be3`.
No approval POST or continuation Operation was issued for this real requirement. Verification is
live API + automated DOM behavior, not a claim of manual browser visual acceptance.

## User handoff

Refresh the existing page to load the new JS contract. The approved knowledge card is read-only;
the user can inspect the saved answer/source and choose the Requirement's Continue action.
Any subsequent delivery/model error is a new execution observation, not evidence that this saved
approval disappeared. Do not rewrite the journal, reset attempts or auto-resume to test the UI.
