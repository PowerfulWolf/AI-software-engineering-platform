# T046 production role queue integration

## Goal
Make existing production request/Console delivery actually execute Coder, QA and Reviewer through the persistent Run queue. Preserve upstream approvals, role independence, candidate verification, serial Task ordering and recovery history.

## Accepted scope
The user approved the integration following a code-backed assessment on 2026-09-19. Start with a single Worker and a complete serial delivery; implement lease heartbeat, safe interrupted execution, knowledge waits and observable queue facts. No new queue stack, same-Task parallel roles, automatic merge or deployment.

## Baseline facts (before implementation)
- TeamHost constructs the queue but production_delivery uses RuntimeSession without queue claims.
- Console already has durable Operations and one asynchronous Manager thread.
- Existing dispatch authority reserves all delivery phases; migration must not silently create two independent capacity authorities.
- A completed queue claim is not a Task verdict; only the existing orchestrator may validate and transition Task.

## Acceptance criteria
- [x] Native and joint production delivery execute each delivery role under an exact real claim.
- [x] One role per claim; no skipped QA/Review or Agent/primary-model substitution. Explicit ordered
  fallback from the frozen policy remains permitted and audited as actual route attempts.
- [x] Heartbeat continues during model work; lost ownership prevents accepted output and advancement.
- [x] Duplicate submissions and restarted execution do not duplicate accepted work.
- [x] Artifact persistence / Task transition / queue completion crash windows are replayable.
- [x] Knowledge waits release capacity and only validated resolution allows continuation.
- [x] Queue and legacy reservation facts cannot overbook or double count capacity.
- [x] Existing terminal Tasks, approvals and historical artifacts stay immutable; documented rollout and rollback.
- [x] Unit/contract/fake e2e, real isolated MySQL integration, lint, strict types, build and independent review.

Implementation verification is complete. Full regression and actual production rollout remain
user-owned; this checklist does not claim paid-provider or independent fleet validation.

## Validation
Use the repository Python 3.12 virtual environment; pytest tests/work_queue, tests/orchestration, tests/manager, tests/knowledge, tests/recovery and existing frontend tests as affected. MySQL tests only in a dedicated explicitly named test database. No paid live model execution needed.

## Rollback
Retain baseline 1879792 and immutable queue/event history. Stop executing processes before switching code;
never reset terminal Tasks or rewrite approvals. Do not execute adopted nonterminal Tasks with an old
binary: drain using the new Worker or freeze delivery until a forward fix. See docs/t046-worker-operations.md.
