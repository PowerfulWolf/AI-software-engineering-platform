# Approved design — bounded automatic coordination

## 1. Scope and research

The user accepted separate service-failure/time-capacity accounting, configurable boundaries,
repair of the existing Manager path, and cross-stage bounded coordination. The user approved
automatic execution of already-authorized safe retries. New execution/repair permissions still require
the existing exact approval. Production resumption remains separately unauthorized for this change.

Existing implementation patterns:

- `manager/verification_coordination.py`: typed, tool-free Manager proposal with exact input digest;
  two calls mean artifact correction, not a durable provider-failure budget. Fixed timeout is 240s.
- `recovery/verification_entry.py:coordinate`: validated QA/executor facts, candidate snapshot,
  immutable advice cache and explicit post-model capability checks.
- `recovery/resume.py:_coordinate_prerequisites`: proposal enters normal exact-plan/repair approval;
  Manager does not execute candidate code or manufacture a verdict.
- `manager/leader_recovery.py`: typed capability registry rejects automatic policy/permission/business
  repair, bounds attempts, and distinguishes direct environment repair from candidate delivery.
- `multi_directory/budget.py` and `service.py`: independent upstream work/transient/capacity counters;
  growth currently fixed at 600/1200/2400s and applied only on a subsequent invocation.
- `web_console/core.py`: one durable user operation is claimed before execution. Generic failures
  currently terminate that operation; only Console interception would miss CLI and restart paths.
- `work_queue/models.py`: current role queue only accepts Coder/QA/Reviewer and requires Task identity.
  Do not masquerade a pre-Task Manager diagnosis as a Coder work item to reuse this queue.

## 2. Approaches and recommendation

**A — Evidence-bound diagnosis + policy-bound action dispatch (recommended).** Add a shared Manager
coordination service below Console/CLI composition. It reads a typed failure snapshot, produces an
immutable advice record, then selects only currently advertised deterministic actions. Already-approved
safe retries may execute within their original authority and budget. New repair/scope/environment
execution follows existing exact approvals. This adds useful autonomy without broad tool authority.

**B — Same diagnosis service, all actions require a click.** Keeps the same data/contracts and provides
explicit recommended actions, but every transient retry needs operator interaction. This is a viable
initial boundary if preferred; it does not meet automatic coordination to the same extent.

Not proposed: a Manager with free shell/store/agent-launch access or a second independent workflow
state machine that can override Product approval and QA/Review.

## 3. Proposed contracts

Implemented APIs (full executable contract in `.trellis/spec/core/manager-coordination.md`):

```python
ExecutionTimePolicy(initial_seconds, max_seconds, max_capacity_timeouts)
ManagerRetryPolicy(max_attempts, max_transient_failures, max_coordination_rounds)
ManagerRunScope(team_id, project_id, requirement_id, stage)
StageBlockage(scope, source_facts_sha256, source_revisions, approval_sha256,
              failure_code, failure_detail, timeout_kind, advertised_actions, child_findings)
ManagerModelExecutor.run(client, *, instructions, payload, model, validate=None)
ProductionStageCoordinator.diagnose(checkpoint, error) -> ManagerCoordinationAdvice
allowed_coordination_actions(policy, checkpoint, error) -> tuple[CoordinationAction, ...]
```

Configuration:

- Manager gets its own artifact-correction, provider-failure and coordination-round limits.
- Manager/Product/Designer/Planner get configurable initial/max local execution windows and capacity
  failure bounds. Fixed 2x geometric growth avoids implying C++ specifies a universal growth factor.
- Common defaults: 600s initial, 2400s ceiling, 3 local timeout failures; preserve existing
  upstream behavior, explicitly increase Manager's old 240s initial window. Manager artifact attempts
  default to 2 (current correction behavior), provider failures to 5, coordination rounds to 3.
- Strict input validation rejects booleans/strings/nonpositive values and ceiling below initial.
  Seconds are limited to 1..86400, counts to 1..100, with contract tests and published Schema.
- Settings changes/restart do not erase counts, change approvals or revive terminal Tasks. Each call
  records the effective policy and chosen window. Existing upstream changes retain current config
  semantics; frozen Delivery Task policy is not retroactively changed.
- Known HTTP/provider failures, transport inactivity and local watchdog expiry are not interchangeable.
  Local expiry never proves useful reasoning. Fallback does not switch routes for local capacity.

Persistence and concurrency:

- Advice reuse is keyed by exact validated input digest; retry/coordination counters are keyed by a
  stable blocked episode, not that changing digest or a fresh Console operation. Updating a checkpoint,
  rewriting a draft or refreshing the browser cannot grant a fresh budget.
- Reserve a unique Manager run before launch, seal typed success/failure afterward. Unknown interrupted
  runs remain uncertain and do not get free refunds. Record work, transient and capacity separately.
- Each real model invocation needs an explicit owner claim with lease/fence checks. Existing Console
  operation claim or a local advice cache alone cannot stand in for an owned Manager role Run. Define
  the pre-Task Requirement-scoped claim additively; do not fabricate a business Task or weaken Delivery
  queue role validation. A dedicated MySQL named lock serializes Manager runs per Team; the new
  `manager_coordination_records` table publishes STARTED and final receipts with before/after fences.
- Include team/project/requirement/stage and source identities. Old advice/checkpoints remain byte/hash
  compatible; never add default fields to historical canonical hashes.
- Manager retry consumes its own budget and cannot recursively dispatch another Manager diagnosis.

## 4. Stage/action matrix

| Facts | Permitted coordination | Forbidden shortcut |
| --- | --- | --- |
| Product discussion failure | Retry same authorized producer within budget, or precise missing-information request | Approve ProductSpec |
| Designer/Planner failure | Diagnose from source/artifacts and typed error; bounded same-stage retry/correction | Return technical uncertainty to Product as new business scope |
| Coder interruption | Existing checkpoint/recovery proposal with exact source/dirty-path checks | Clear terminal state or accept unsealed dirty changes |
| QA FAIL / Review REJECT | Existing typed findings route to Coder; coordinate actual missing prerequisites | Retry a valid negative verdict until approval |
| Inconclusive verification/executor failure | Existing Manager UI/prerequisite proposal and exact approval | Reuse consumed approval or claim independent PASS |
| Provider/auth/config/permission failure | Typed retry if permitted; otherwise concrete operator action | Ask for secrets, edit policy or expand rights |
| Budget exhausted / unknown interruption / unverifiable facts | Stop with auditable owner/action/resume condition | Unbounded retries or speculative repair |

Model text cannot change trusted failure classification, add an action absent from the allowlist,
select an arbitrary role, or override the underlying service's current-facts/approval guards.

## 5. UI and documentation

- Correct Manager route description: active intelligent coordination, with deterministic execution gates.
- Separate compact retry-count and execution-time groups in Basic settings; use existing aligned fields
  and explanation icons. No redesign of unrelated MySQL/model catalog sections.
- Show original delivery stage independently of Manager diagnosis/retry/wait state. Display exhausted
  budget type, configured ceiling, actual next window and concrete required action.
- An approval remains an approval; never replace it with a generic retry button.
- Update AGENTS retry paragraph, overview, production-host and execution-retry specs; retain historical
  verification capability rules rather than replacing their boundary with prose-only policy.

## 6. Validation and examples

Good: Planner local timeout produces a sealed capacity fact, Manager schedules only a still-authorized
same-stage retry with doubled window; new claim, unchanged Product approval, no transient debit.

Base: unchanged failed verification input after restart reuses stored advice; no extra model or executor.

Bad: malformed advice invents shell commands, selects a role outside advertised actions, auto-approves
repair, resets budget by varying prose, or treats a valid QA FAIL as a provider failure. Reject all.

## 7. Existing data / rollback

No production records are changed during development. Old timeout history is not retroactively
classified. On rollout, new records append to existing history and current-blockage inspection produces
new advice only where facts can be verified. Terminal delivery still requires normal recovery and new
exact approval where applicable. Document concrete resume steps with final code, not direct DB edits.

Rollback must preserve any new coordination ledger for audit; stop executions before reverting code.
After new advice/config publication, old strict readers may reject new fields. Prefer a compatibility
fix or a consistent verified pre-rollout backup while retaining newer audit history separately; never
strip fields and recompute hashes. No automatic-dispatch toggle is claimed or implemented.

## 8. Implemented scope and limitations

- Shared execution budget covers production candidate-verification Manager calls and standard
  Console/`ase request` cross-stage diagnosis; legacy native `ase project` upstream is unchanged.
- The initial cross-stage context is typed failures, source/approval hashes and child checkpoint
  findings. Manager has no arbitrary code-reading, shell, database or role-launch capability.
- CLI ownership loss terminates its process group. Responses calls cannot be cancelled mid-HTTP
  request, but late/unowned results cannot publish.
- Team serialization is conservative; contention returns an actionable coordination stop. No new
  parallel worker/fleet, unlimited retry or independent approval authority is introduced.
