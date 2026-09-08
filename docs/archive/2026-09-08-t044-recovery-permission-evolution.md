# T044 D4 — Recovery permission evolution

## Bug analysis

### 1. Root cause category

- **B — Cross-layer contract**: one `RecoveryPlan.permissions` field represented both the historical
  policy needed to verify the interrupted worktree and the current policy needed to start a new Coder.
- **D — Test coverage gap**: recovery integration tests used the same command policy before and after
  interruption, so a later platform security tightening was never exercised.
- **E — Implicit assumption**: execution assumed a failed Task's permission snapshot would always equal
  the current delivery policy.

The assumption became false when direct `git add`/`git commit` authority moved from Coder to the
platform-owned CandidateCommit Skill. Recovery proposal and approval succeeded, but allocation then
compared the current safer AgentDefinition with the historical wider permissions and stopped before
worktree creation or model invocation.

### 2. Why earlier checks did not catch it

Unit tests proved immutable plans, current-fact validation and exact permission equality independently.
End-to-end tests proved recovery under a stable policy. None crossed a policy version boundary, so the
same exact-equality check appeared safe in every fixture while making a real approved plan inherently
unexecutable.

### 3. Prevention mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Architecture | Separate source capture permissions from hash-bound target execution permissions | DONE |
| P0 | Runtime guard | Permit only conservative exact-token narrowing; reject expansion and network changes | DONE |
| P0 | Current-fact gate | Recompile target permissions before execution and exact-match the approved target | DONE |
| P0 | Integration test | Start under legacy direct-commit policy, recover under CandidateCommit policy, reach independent QA/Review | DONE |
| P1 | Review checklist | For every recovery snapshot field, distinguish historical evidence from current authority | DONE in recovery spec |

### 4. Systematic expansion

Recovery records often bridge two times: the failed run and the new run. A field that is both evidence
and authority is a warning sign. Model/provider selection, denied paths, context budgets, tool policies
and spec revisions should be reviewed with the same question: which values prove history, which values
authorize the target, and which transitions are allowed? Exact equality is correct within one temporal
role; it is not automatically correct across both roles.

### 5. Knowledge capture

The executable contracts, validation matrix, Good/Base/Bad cases, tests and wrong/correct examples are
recorded in `.trellis/spec/core/delivery-recovery.md` D4 and summarized in `docs/contracts.md`. This
repository has no `.trellis/spec/guides/` or `src/templates/markdown/spec/` tree, so there is no guide
template to synchronize; the domain-specific core spec is the canonical project location.

## Change

`RecoveryPlan.permissions` remains the historical source policy. Optional `target_permissions` records
the current Coder policy and participates in the exact plan SHA and human approval. Legacy plans omit
the field and retain their digest. New proposals compile target permissions from the current
ProjectProfile plus original allowed paths. Execution and current-fact validation both require exact
agreement with `effective_target_permissions`.

The target can only remove exact read/write/command entries and must keep the same network class. It
cannot gain state-change or merge authority. A stale legacy approval after policy tightening is not
upgraded in place: it is rejected and requires a new proposal and exact approval.

## Verification

- Full regression: **946 passed / 448.83s**, using the dedicated MySQL test database and offline
  scripted providers; no live model quota was consumed.
- Real Git/MySQL recovery passed ordinary, clean-base reapplication, legacy-direct-commit narrowing,
  joint parent/child context and original-history preservation scenarios.
- Ruff format/check passed for 544 files; strict Mypy passed for 299 source files; `uv lock --check`,
  `git diff --check`, source distribution and wheel build all passed.
- The exact historical production plan remains immutable and will be superseded by a new proposal only
  after this platform fix is committed and the target repository is updated.
