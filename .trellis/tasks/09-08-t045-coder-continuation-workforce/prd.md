# T045 — Recoverable Coder continuation and durable organization roster

## Goal

Allow a bounded Coder run to stop cleanly, persist verifiable progress, release execution, and be
resumed by the same organization team until a candidate is complete. At the same time, materialize
Project Manager, Product, Designer, and Planner as durable organization-owned members instead of
creating only the delivery trio at dispatch time.

## Requirements

- Extract platform-owned candidate creation from the Codex adapter into an explicit typed
  `CandidateCommitSkill` with exact base revision, changed-path inventory, write-policy, clean-index,
  hook-free and non-interactive Git checks.
- Add an immutable `coder-progress` Artifact produced only by Coder. It binds the Task/run/context,
  current source revision, changed paths, completed/remaining plan steps, tests and next actions.
- Accept either `coder-progress` or `implementation-report` as Coder output. Progress is never a
  candidate and cannot unlock QA.
- Persist and replay the exact continuation loop
  `IMPLEMENTING → CONTINUE_REQUIRED → QUEUED → IMPLEMENTING`; every edge is an orchestrator-owned
  StateEvent and every resumed run receives the persisted progress Artifact.
- A continuation run may reopen only an exact, policy-authorized dirty Coder worktree matching the
  persisted checkpoint. Drift, timeout with unsealed changes, unauthorized paths, or exhausted
  attempt budget fails closed and preserves evidence.
- Bootstrap durable organization AgentProfiles for Project Manager, Product, Designer, Planner,
  Coder, QA, and Reviewer. Scheduler, ModelRouter, and Orchestrator remain deterministic services and
  are not represented as model team members.
- Keep a single Task serial: Coder continuation completes before QA, then Reviewer.

## Acceptance Criteria

- [x] CandidateCommitSkill finalizes a valid provisional implementation and rejects base drift,
      changed-path mismatch, unauthorized writes, mixed commit-plus-dirty state, and empty diff.
- [x] `coder-progress` validates in Python and Draft 2020-12 JSON Schema and cannot be produced by
      another role.
- [x] An offline fake run can emit progress, traverse the three continuation states, resume with the
      exact checkpoint, then produce a candidate and complete QA/Review.
- [x] Restart from `CONTINUE_REQUIRED`, `QUEUED`, or an already-persisted progress Artifact resumes
      without overwriting the checkpoint or skipping QA.
- [x] Codex CLI accepts only the dirty-path set bound to the continuation request and invokes the
      CandidateCommitSkill only for a successful implementation report.
- [x] Organization workspace contains seven stable AgentProfiles before the first dispatch; team
      projection can show the four upstream members as idle when they have no run allocation.
- [x] Targeted tests, full pytest, Ruff, strict Mypy, schema registry, build, and git diff check pass.

## Definition of Done

- Python models, JSON Schemas, docs, AGENTS.md, and Trellis core specs describe the same contracts.
- Good/base/bad tests cover artifact, state, restart, Git policy, roster idempotency, and role
  independence.
- Existing unfinished candidate-finalization work is preserved and superseded by the explicit Skill
  seam rather than discarded.

## Out of Scope

- Parallel roles inside one Task, distributed queues, message brokers, vector databases, automatic
  merge/push/deploy, and unbounded continuation.
- Reporter Agent.
- Replacing deterministic Scheduler, ModelRouter, or Orchestrator with LLM agents.
