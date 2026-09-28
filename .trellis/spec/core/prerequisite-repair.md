# Source-changing prerequisite repair through ASE

## 1. Scope / Trigger

Use when independent QA is inconclusive or a sealed controlled executor fails before a verifier
model, and fixing the test prerequisite requires repository changes. The operator maintains ASE,
not the business candidate. Never turn NOT_TESTED into a
fabricated business FAIL merely to route to Coder. Automatic environment repair and explicit
source-changing repair are different capabilities.

## 2. Signatures

`ContinueDeliveryIntent` / `ResumeProjectDelivery` add mutually exclusive optional fields:

- `prerequisite_repair: {objective, write_paths}` proposes, without invoking any model.
- `approved_repair_sha256` approves only the exact saved repair; it needs an approval reference
  in the internal command. Console supplies the auditable `web-console-repair:<sha>` reference.

`PrerequisiteRepairPlan` binds source QA completion/incident/Task/candidate, native checkpoint,
target clean base/preparation and requested paths. `FileRecoveryStore.put/get_repair_plan` and
`put/get_repair_authorization` use the existing private append-only store.

Alternative source: `CandidateExecutorPrerequisite(plan_sha256, source_task_id,
candidate_revision, execution_failure, observed_at, observation_sha256)` is a sealed observation,
not `CandidateVerificationCompletion`. `record_executor_prerequisite(receipt)` and
`get_executor_prerequisite(sha256)` validate the admitted BLOCKED receipt and reject completed
verification sources. `CandidateRemediationEvidence` is the explicit union of these two types.
`PrerequisiteRepairPlan` requires exactly one of `completion_sha256 + incident_sha256` or
`executor_prerequisite_sha256`. Optional `manager_advice_input_sha256` binds a Manager proposal.

## 3. Contracts

- Pending verification may refer to the most recent sealed inconclusive result. Proposal/approval
  does not alter it. Verified candidates and business-rejected reports do not qualify.
- Repeated same proposal and current facts reuse one digest. Different scope/objective/base changes
  the digest. Approval must be separate; verification/scope/repair grants cannot be combined.
- Validate private store integrity, source incident, current Task/candidate/checkpoint, target base
  and preparation before publication/admission. Preserve denied paths and command/network policy.
  Scope permits explicit relative files or named subdirectory `/**`, never traversal, hidden policy
  directories, repository-wide globs or AGENTS.md/CONTEXT.md.
- The ordinary `CandidateRemediationService` now accepts an exactly approved prerequisite repair.
  It creates a NEW Task and three distinct serial Coder/QA/Reviewer assignments. The distinct
  continuation kind is `prerequisite_repair`; its identity uses the repair plan digest, while
  `continuation_sha256` references the actual typed source evidence digest. No fake Planner run
  or QA report is created.
- Manager coordination v4 can return `PROPOSE_REPAIR` with `prerequisite_repair`, only when a
  sealed executor source is available. This is proposal-only, not approval. Store validates the
  exact request, candidate and execution reference against the repair source. Current facts and
  target preparation/base are checked again before admission. Existing explicit QA-source repair
  remains supported. UI marks executor evidence as non-QA, never displays a fabricated incident.
- Preserve all actual QA/Reviewer invocation IDs when validating a failed repair successor:
  a Reviewer executor may fail after QA admission. Unknown extra run IDs still reject drift.
- Required `manager.prerequisite_repair` context binds the full approved objective. The original
  candidate patch is preserved as context for Coder to adapt onto the approved current base.
  Never import an operator-authored business patch. Original acceptance criteria remain required.
- Restart reconstructs repair context from stored proposal/authorization, not from conversation.
  Approval/dispatch are exact and idempotent; scope execution lock prevents concurrent repair starts.
- New candidate uses ordinary CandidateCommit and independent QA/Review. Build/test or Operation
  success is not delivery DONE. Additional GUI/tool capability requires separate exact approval.
- Historical records omit optional absent fields and preserve digests. No direct Task/DB/verdict
  edits, automatic merge, credential access, installation or deployment are authorized.

## 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Proposal only | REPAIR_APPROVAL_REQUIRED; zero Coder calls |
| Repeated same proposal | Same digest/checkpoint |
| Wrong/missing approval or stale source/base | Reject; zero Coder calls |
| Only NOT_TESTED/ERROR without repair approval | Ordinary same-candidate verification proposal |
| Exact repair approved | Ordinary fresh serial Task; source facts preserved |
| Candidate complete, UI still unavailable | No manufactured PASS; Manager handles next prerequisite |
| Changed file scope | New proposal, never reuse old authority |
| Executor-source proposal without a final admitted BLOCKED receipt | Reject, zero Coder calls |
| Completed verification relabeled as executor prerequisite | Reject on write and readback |
| QA and executor source fields mixed | Pydantic and canonical JSON Schema reject |
| Manager proposal request/receipt differs from repair | Reject |

## 5. Good / Base / Bad Cases

Good: Manager proposes mock entry, delegated operator reviews exact scope, ASE Coder implements,
independent verifiers accept the resulting SHA. Base: proposal waits without model execution.
Bad: operator manually writes the business patch and reports its local tests as platform QA.

## 6. Tests Required

- `test_prerequisite_repair.py`: Console red-capable input, exclusivity, safe paths, store
  restart/tamper, exact authority and repeat proposal without Coder.
- `test_prerequisite_repair_mysql.py`: isolated MySQL + real Git; inconclusive QA, human gate,
  executor block before QA, admitted Coder/QA/Reviewer, new candidate, original BLOCKED Task
  retained, zero-call replay; both sources with and without restart before Coder.
- `test_executor_prerequisite.py`: QA/Reviewer executor failures, no manufactured completion,
  separate approval, immutable readback/tamper, source/scope/unknown-run drift rejection,
  Manager proposal-only controller and non-QA Console facts.
- Existing continuation/host/Console regressions; lint/types/diff. Regenerate schemas with
  `scripts/generate-verification-schema.py` and `scripts/generate-repair-schemas.py`.
- MySQL requires a separately validated `ASE_TEST_MYSQL_DSN`. Never use production facts in tests.

## 7. Wrong vs Correct

Wrong: edit source in an operator checkout or reinterpret inconclusive QA as a business defect.
Correct: propose → review exact repair scope → persist approval → ordinary ASE Coder → new SHA →
independent QA/Reviewer → normal parent continuation. The operator changes platform mechanisms.
