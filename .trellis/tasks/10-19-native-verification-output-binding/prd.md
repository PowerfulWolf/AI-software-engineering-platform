# Bind native verification output to trusted execution receipts

## Goal
Before a native QA/Review report can be accepted, require its references to bind the actual
trusted controlled-verification receipt delivered in that exact request. Keep the current K1
implementation running and preserve its already accepted progress and historical declarations.

## Observed gap
K1 Run2 progress has four model-authored command URI/SHA declarations with no corresponding
machine CommandEvidence. Native Coder tools do not currently retain a replayable command
transcript; accepted progress therefore proves preserved draft/continuation, not those tests.
Production independent verifiers do execute controlled tests and seal real receipts, but their
report acceptance does not currently require references to match the receipt. Fix that latter
bounded gap using the existing typed provider seam. Do not invent historical evidence.

## Scope / ownership
- Implementation worker run6: native output contract, internal prompt transport, real provider
  composition, focused unit/contract tests, no persisted or exported Schema changes.
- Root: task, executable spec, integration, deployment at an idle boundary and existing K1.
- Independent reviewer: source/spec and targeted checks, no production control or verdict edits.
All use `/tmp/ase-fix-legacy-ignored`. Workers share the checkout and must preserve other edits.
Real K1 worktrees and durable records remain read-only to maintainers.

## Acceptance
- Add a deterministic regression exercising real native adapter output acceptance: a model PASS
  with a self-consistent evidence array but wrong/missing trusted receipt must be rejected.
- Internal typed contract binds the complete request and real receipt identities, task/run/role/
  context/candidate plus admitted claim where applicable; never derive trust from prompt text.
- QA required coverage and current tests, and Review's cited evidence, reference exact trusted
  URI/SHA. Background evidence from genuine upstream artifacts remains permitted.
- Machine execution success does not generate or amend a role verdict. Missing/contradictory
  proof rejects before result publication through safe existing failure behavior.
- Production Python/MySQL and existing Swift/UI controlled paths derive contracts from their
  actual typed plans/receipts. Fake, ordinary source inspection and legacy unbound paths retain
  compatibility. A newly controlled provider must not silently omit its contract.
- Internal metadata is absent from provider wire, persisted artifacts, public Schemas, historical
  hashes and approvals. No new SQL/IPC/log transcript, Coder command authority or model authority.
- Preserve all fresh authorization/claim/workspace/execution guards; no cached approval/READY
  or replayed executor call to validate output.

## Validation / stored data / rollback
Run focused red then green native-adapter tests with real temporary Git and offline responses,
provider-composition/compatibility regressions, Ruff/format/strict Mypy and independent review.
Do not run production control or interrupt an active K1 role to deploy. Existing model-authored
test claims stay immutable and unverified. At candidate verification use new independent runs,
exact candidate-bound plans and new actual receipts; never reuse or relabel the old claims.
Deployment waits for a controlled idle boundary. Rollback reverts the admission guard while
retaining every original report, failed output, approval and execution receipt.
