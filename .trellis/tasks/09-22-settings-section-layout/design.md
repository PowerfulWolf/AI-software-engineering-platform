# Execution and retry policy design

## Decision

Use a typed operator-owned execution policy, not a single global retry number. Product discussion,
Designer/Planner artifact attempts and Coder iterations have different meanings. QA/Reviewer findings
send work back to Coder; they must not be retried to obtain a favorable verdict. Manager currently
dispatches deterministic skills, so it has no model-call allowance.

Upstream stages keep append-only Requirement attempt counters, with distinct typed transient keys.
New native Tasks freeze delivery retry policy at dispatch and persist typed transient failure facts
with the Task. The existing monotonically increasing attempt remains an execution identity, not the
work budget: logical work attempt = execution attempt minus recorded transient failures. Existing
Tasks without a frozen retry policy retain their original limit and recovery approvals.

The transport attempt ceiling must accommodate bounded work plus all role transient allowances;
all attempt-bearing domain, context, evidence, queue and wire contracts must stay aligned. Database
Task JSON can hold optional policy/failure fields without altering old immutable artifacts.

## Alternatives rejected

- Rename Design controls as global without wiring execution: misleading and ineffective.
- Reuse Task.max_attempts as every role's allowance: still lets QA timeouts consume Coder corrections.
- Retry inside an admitted provider Run or reset Task attempts: breaks at-most-once/evidence lineage.

## Safety and acceptance

- Keep pre-invocation reservation, real Worker claims, finite limits and strict typed classification.
- Persist each failure once, bound to role, attempt and run identity; reject conflicting replay.
- No role permissions, worktree approval, verdict or terminal Task gate is weakened.
- Operator changes affect resumed upstream stages and new Tasks; never silently mutate old Task scope.
- Legacy Design configuration is accepted and mapped to the canonical Designer policy.
- Test with fake providers and temporary journals/SQLite plus existing fenced MySQL repository seams;
  do not execute production DB writes or providers. Only changed-path tests, no full suite.
