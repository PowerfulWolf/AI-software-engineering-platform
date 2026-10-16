# Original K1 verification readiness — 2026-10-16

This is a read-only preparation finding at platform main017ac97, not a new execution
approval, a preflight result, or a finding that the healthy Run6 is blocked. No active
Coder checkout was inspected or changed. The existing frozen Product/Design/Plan remain
the acceptance authority; the maintainer cannot replace independent QA/Review.

## Frozen acceptance sources

ProductSpec `product_spec_867a271f104e28296498aeef`, TechnicalDesign
`technical_design_5f28e09b9172eccf3615674e` and ExecutionPlan
`execution_plan_39a66178a033b6a829dbf725` contain 25 acceptance criteria and 61 test-level
records. The execution plan's `record.work_graph.packages[].tests[]` contains the full
mapping: 32 distinct exact nodes assigned to the controlled Python/MySQL capability and
five e2e records. The current recovery
plan `art_plan_7b9c6b2d8a4e0855a2b16f77` retains `content.acceptance_mapping` and
`content.verification_requirements` on frozen source774e0a6fcc920d9a6ce3738e80b9cc43045be7eb.

These immutable records are in the registered repository sidecar for
project_ai-project_034252eb3595 / repository_c78e1680f621ff06c808aa9559666412444fbd7b:
`state/product/specs/request_c833c3235d0bb73adba67937d16ea66c/00000001.json`,
`state/design/designs/technical_design_5f28e09b9172eccf3615674e.json`,
`state/planning/execution-plans/execution_plan_39a66178a033b6a829dbf725.json` and
`artifacts/art_plan_7b9c6b2d8a4e0855a2b16f77.json`. The independent acceptance researcher
verified their integrity; this document is a navigation aid, not replacement evidence.

Product criterion ac_012_001 requires an accepted A report to generate a proposal without
manual collect, followed by exact authorization, publication/selection and a new B role
Run performing search/read and citing the same knowledge. Its evidence includes A acceptance
and collection, proposal/authorization SHA, publication and selection, B's actual Run/claim,
search/read evidence and same-Run document/chunk SHA citations.

The recovery plan explicitly says:

> 组件测试不能替代真实 provider、claim、用户授权和 B 的 search/read/citation。

Its mitigation requires retaining integration/e2e levels and an external real manifest;
missing facts stay unverified, rather than using fixtures or Context injection to claim success.
The frozen execution plan classifies production composition with component fixtures as
integration. Fake role adapters may supply integration evidence, but cannot alone satisfy
the frozen real A→B e2e.

## Existing execution boundaries

- Registered Python/MySQL execution binds exact pytest nodes, candidate and native independent
  role claims. It disables network and only permits its private MySQL Unix proxy.
- Swift Mock AX execution is bounded and requires Swift build capability. It is not Web
  Playwright execution.
- Source prerequisite repair needs its own sealed prerequisite facts and exact authorization;
  it does not grant new browser or network capabilities.
- `ContinueDeliveryIntent` has no Playwright, ASE live-environment or human-run verification
  evidence import field. `VerificationEvidenceProvider` is an internal trusted seam; arbitrary
  maintainer screenshots/logs have no public independent acceptance route.
- Existing `tests/team_view/browser/fixture.cjs` launches real Playwright/Chrome with fixture
  API responses. It supports actual rendering/interaction checks, not proof of the real backend
  or A→B. Independent QA must assess it together with the other criterion evidence.

See `.trellis/spec/core/verification-environment.md`, `prerequisite-repair.md` and
`active-knowledge.md`; implementation entry points are `manager/native_verification.py`,
`manager/native_verification_store.py` and `recovery/verification_execution.py`.

## Follow-up and existing data

The frozen plan already states the real browser and production A→B execution prerequisites
are unproven. This research ran no new preflight and does not make that a current Run6 failure.
Let the original healthy Coder continue. Once a real candidate reaches native verification
preparation, use actual preflight facts to determine whether additional capabilities are needed.

If needed, propose narrowly scoped, versioned, exactly approved trusted execution for the fixed
browser and ASE live scenarios, bound to candidate, ACs, toolchain/runner/policy and isolated
resources. Preserve STARTED/final receipts, real process ownership, resource cleanup, unknown
execution refusal and independent native QA/Review consumption. New authority must not silently
expand old policy. A maintainer's successful run or click is not a native verdict.

No SQL migration, Task/approval mutation, source rebase, new scheduled task or K1 execution
intervention is required by this document. Rollback only removes this navigation document;
all original artifacts, outcomes, approvals and execution history stay unchanged.
