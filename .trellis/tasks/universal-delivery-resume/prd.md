# Universal delivery resume

## Goal

Make `ase request resume <delivery_id>` the normal recovery entry for an interrupted
requirement delivery at any persisted stage. Project Manager must inspect durable facts and continue
through the correct successor run/attempt until delivery completes or reaches an explicit human gate.
Low-level `verify-*` and `recovery *` commands remain internal/break-glass capabilities.

## What I already know

- Resume must target a delivery aggregate because Product/Designer stages can precede Task creation.
- One Agent Run remains at-most-once; a Delivery continues through new successor runs and attempts.
- Infrastructure failure retries the same role with a new run identity.
- QA FAIL or Review REJECT creates Coder remediation with the prior report as required context.
- Terminal facts are immutable; resume must not reset an old FAILED/BLOCKED Task.
- Multi-repository delivery retains completed children and resumes only incomplete children.
- Human approval, spec conflict, policy/source drift and exhausted attempt budgets remain human gates.
- The live team view omitted the QA verification work item during the real `verify-run` for plan
  `7b7d1166...`; the read model must expose recovery/verification execution and directory scope.
- The real candidate `dcc2ab1...` produced a valid QA FAIL for Schema/model path parity and will be
  the acceptance case for QA -> Coder remediation -> Candidate V2 -> QA -> Reviewer.

## Assumptions

- v0.1 uses existing MySQL, file sidecar, WorkQueue, Scheduler, ModelRouter and serial runtime.
- No complex DAG, new message broker, vector database or new Agent role is introduced.
- The existing four low-level candidate verification commands stay available for audit and recovery.
- `resume` may return `WAITING_HUMAN` with a precise action instead of bypassing approval.

## Requirements

- Add one idempotent Project Manager resume controller over persisted delivery/joint/runtime/recovery
  facts, with a typed classification and next action.
- Resume pre-Task Product/Designer/Planner interruptions from the latest immutable checkpoint.
- Resume dispatch/Lease and Coder interruptions without repeating an admitted provider invocation.
- Route transient QA/Reviewer infrastructure failures to a fresh same-role run.
- Route QA FAIL and Review REJECT to a linked Coder remediation attempt with report evidence.
- Continue multi-repository parents while retaining completed child deliveries.
- Return existing completion for DONE deliveries without side effects.
- Expose active verification/recovery/remediation work, assigned Agent, role, stage, run/task identity
  and selected directory scope in the live team view.
- Keep every state transition, plan, approval, invocation and Artifact auditable and replay-safe.

## Acceptance Criteria

- [x] One public resume command classifies and continues every currently implemented persisted stage.
- [x] Repeating the same resume request does not duplicate Task, Assignment, Lease or Agent invocation.
- [x] RATE_LIMITED verification produces a fresh verifier run against the same candidate.
- [x] QA FAIL creates a Coder remediation using the sealed QA report and produces Candidate V2.
- [x] Review REJECT follows the same remediation contract using the sealed Review report.
- [x] Approval/spec/policy/source conflicts return a typed human gate with zero provider calls.
- [x] DONE replay returns the same delivery result with zero provider calls.
- [x] Joint delivery resumes only incomplete children and preserves completed child facts.
- [x] Live view shows an active QA/Reviewer verification reservation and its repository directory.
- [x] Offline unit/contract/integration/e2e tests, Ruff, format, Mypy and package build pass.

## Definition of Done

- Executable code-specs include signatures, record fields, state/error matrix and Good/Base/Bad cases.
- Regression tests reproduce the real missing-verification-work-item symptom and QA remediation path.
- README primary usage is simplified to resume/status; low-level commands move to troubleshooting.
- No live model call, automatic merge, push or deployment is required by implementation tests.

## Out of Scope

- Parallel phases inside one Task, distributed queue infrastructure or Kubernetes deployment.
- Automatic relaxation of policy, privacy, approval or project-native specification conflicts.
- Silent retry of an invocation whose provider completion is uncertain.
- Reporter Agent and automatic merge/push/deploy.

## Technical Notes

- Relevant modules: `project_manager/delivery.py`, `multi_directory/service.py`, `recovery/`,
  `work_queue/`, `team_view/reader.py`, `team_view/models.py`, CLI and production composition.
- Relevant specs: architecture, contracts, Python runtime, production Team Host, persistent WorkQueue,
  delivery recovery, multi-directory delivery and live team view.
