# 2026-09-25 — slice 1 verification / handoff

## Implemented in current ASE checkout

- Bounded, evidence-referencing discoveries in implementation, QA and Review report contracts.
- Hash-compatible legacy report omission, provider prompt guidance and strict transport fixtures.
- Explicit Project collection into pending observations, redaction, exact source revalidation at
  approval, immutable human authorization, background publication and future-context retrieval.
- Fixed knowledge-resolution JSON Schema drift and frontend provenance rendering; added owner,
  applicability, role/revision, source SHA and URI display. Background is the first publication action.
- Fixed publication/selection RMW race with scope lock; concurrent-deselection test passes.
- Persisted domain vocabulary, lifecycle audit and executable spec; all pre-existing repair changes
  retained. No code commit, production service restart, DB mutation, live model run or verdict change.

## Actual results

- Combined Python affected suite: **552 passed, 1 deselected** in 14.01s. The deselected case requires
  isolated MySQL; this slice does not change its schema/queue. Domains, artifacts, contracts, specs,
  agents, knowledge, Console administration/transport and orchestration covered.
- Added actual HTTP collection → pending → stale approval refusal → exact approval → knowledge display
  regression afterward: **1 passed** in 0.67s. Total distinct passing Python cases: **553**.
- Node frontend plus isolated Playwright/Chrome: **54 passed**, including five browser scenarios.
- Strict mypy: **9 files passed**; Ruff check/format and `git diff --check` passed.
- Two dependency deprecation warnings (Starlette/httpx and anyio alias) remain. No dependency upgrade
  was performed as part of this behavioral correction.
- Initial local Playwright resolution failed; using the already bundled dependency path ran the
  tests successfully. No installation or production browser-session use was needed.
- These are local regression checks, not independent live QA/Review approval of this patch and not
  proof that the quota-monitor Requirement is DONE.

## Root-cause review

1. Category: change propagation + cross-layer contract + missing scenario coverage. Learning
   implicitly meant failed verification, so approved answers and ordinary discoveries were omitted.
2. Why isolated fixes were insufficient: a Python model/store test did not exercise JSON Schema,
   frontend source variants or later requirement retrieval. An interface definition did not prove
   production composition. No claim that Xcode resolves these platform issues.
3. Prevention implemented: all report/evidence variants, schema mismatch refusal, source-tamper
   rejection, public HTTP round-trip, browser provenance, per-role future reads and concurrency tests.
4. Broader remaining issue: learning collection is still explicit; automatic accepted-checkpoint
   capture, upstream producers, Manager prerequisite resolution and governed capability promotion
   are not implemented by this slice.
5. Knowledge captured: `.trellis/spec/core/project-learning.md`, core contracts/index/Console spec,
   `docs/contracts.md`, `CONTEXT.md` and this task's lifecycle audit.

## Existing data / next required work

No migration or direct database repair. Deploy compatible code before collecting new observation
fields; the Project learning page can explicitly collect persisted reports. Do not invent discoveries
for historical reports that never recorded them. Prepared/approved requirements remain frozen.

Overall task stays **in_progress**. Next implement durable Manager prerequisite incidents and exact
resolution/readiness recovery without repeated impossible QA; then accepted-checkpoint automatic
capture and upstream role discovery production. Keep these distinct from the existing Swift-specific
verification policy. The original delivery remains blocked pending genuine required verification.

Rollback: revert only this task's changes while preserving prior dirty fixes. After new observation
records exist, retain compatible readers or roll forward; do not erase artifacts/history to downgrade.
