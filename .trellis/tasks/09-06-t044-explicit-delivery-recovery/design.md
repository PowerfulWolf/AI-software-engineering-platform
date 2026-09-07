# T044 increment B — durable recovery intent, not execution

## Confirmed goal
User confirmed continuing after being told the directory requirement is not delivered. Build the
next prerequisite without paid Agent calls or editing the original Coder checkout.

## Design
`RecoveryPlan` embeds a wire-safe capture and exact failed-source references, target base/preparation,
permissions and creation time. Hash binds every field. It is a proposed new execution, never an edit
of the failed Task. `RecoveryApprovalCommand` names the exact plan and trusted-channel reference;
`VerifiedRecoveryDecision` comes only from an injected human verifier, not a model.

`RecoveryAuthorizationService` receives a scoped `RecoveryStore`, current-fact verifier, capture
verifier and human verifier. Propose checks facts/capture before storage. Authorize checks before
and after verification, then publishes one complete immutable receipt. Exact completed replay reads
the original receipt without external calls. `require_current_authorization` rechecks facts/capture,
so replaying an approval never silently grants permission against drifted code or baseline.

Use one plan file (embedded capture) and one decision receipt per plan digest. Store paths are flat,
scoped to company/project/failed delivery and outside project code. No-follow directory/file fds,
inode checks, bounded reads, private permissions, exclusive hard-link publish and fsync protect
append-only facts. Constructor reads existing root; explicit initialize creates only one child of an
existing sidecar directory. No generic writes, overwrites or silent root repair.

## Cases / contracts
- Good: real Git capture, fake trusted verifier, close/reopen store, exact replay with verifier offline.
- Base: rejected human decision is durable but cannot pass the execution gate.
- Bad: forged decision identity, changed plan/command/source/capture, secret/tampered JSON or symlink.
- Receipt-first interruption: an already published full receipt is replayable; no secondary effects.
- Before receipt: external verifier must itself be idempotent by the exact command; do not claim
  exactly-once external execution across an unrecorded process crash.

## Scope
New `recovery/{models,store,service}.py`, package exports, schema, tests, docs/contracts.md, recovery
spec, archive and task files. Reuse WorktreeChangeCapture/Git manager, AgentPermissions, shared IDs,
DomainModel and secret scanner. Existing product/design store patterns inform implementation but
their private helpers and domain-specific errors are not a reusable storage API.

Production fact-reader/human-channel adapters, CLI, target preparation, new Task/dispatch, patch
application and actual model delivery remain the next increment. Do not construct fake upstream
approvals to make recovery appear integrated.

## Increment C1 — native source inspection

Implement `NativeRecoverySourceReader(config, environment).inspect(scope, *, failed_run_id,
failed_context_id) -> NativeRecoverySource`. Resolve the selected company/project manifest, terminal
native checkpoint, one read-only consistent MySQL Task/events/dispatch snapshot, exact Product
approval/Design/Planner records, original preparation and failed Coder context/route. Return typed
in-process source facts and approved content, never an execution permission. Discover joint ownership
from the existing company journal; omission by a caller cannot discard parent approval lineage.

Add explicit `read_only=True` to existing upstream stores instead of duplicating their file formats.
Reads cannot initialize missing roots; writes/fences on read-only instances reject. Reuse native
integrity/stage-chain validators and SQL row decoders. No schema change, model call, new preparation,
source-branch modification or Task mutation. New target/current rules and human authorization are still
separate prerequisites; the source reader must not masquerade as a complete RecoveryFactsVerifier.

Good: a real Git/MySQL delivery stopped by an offline Coder yields exact source hashes without writes.
Base: reopening gives the same result. Bad: wrong company/checkpoint/Task/run/context, missing approval,
modified native payload, future request revision or non-Coder failure rejects with a safe error.
Verify with upstream store read-only contracts and offline production fixtures; all historic bytes and
SQL revisions remain unchanged. Rollback is an isolated source commit; no database migration.

## Increment C2 — seed a fresh Coder worktree

`GitWorktreeManager.seed_changes(capture, target, source_permissions, target_permissions,
*, source_denied_paths=(), target_denied_paths=()) -> WorktreeChangeCapture` is a lower-level repository
operation, never Agent/human authority. The future application caller must authorize the exact
RecoveryPlan and target preparation, materialize a NEW Task/dispatch and create its worktree first.
This increment uses only temporary test worktrees; no live recovery seed is authorized or performed.

Require a different Task, Coder role, attempt 1, exact registered branch/full target SHA, clean target
and original capture revalidation. Target must descend from the original base. Enforce both source
and target policies on every path. Reject custom merge drivers/attributes; use controlled Git three-way
application of the verified full-index patch, with zero-context support and preflight. No fuzzy/manual
conflict resolution, commit, source staging, ref rewriting or reset. Changed files in newer main are
retained when Git merges without conflicts. Return a newly verified target capture for later sealing.

Good: independent newer-base edits plus preserved Coder changes; old files/index/HEAD unchanged.
Base: same original base, empty capture or already-applied edits; never infer a candidate.
Bad: conflict, changed source, dirty/forged target, unrelated base, narrowed policy, custom driver.
Preflight rejection leaves target content/index unchanged. A failure after actual application retains
the new target for diagnosis; no cleanup/rollback. Replaying seed into dirty work is forbidden; later
receipt-aware recovery must verify the exact returned capture instead. No production CLI/provider dirty
admission is added here. Test real Git, failure/race injection, source/index preservation and no model use.

Implementation correction: `git apply --check --3way` does not reliably reject merge conflicts.
Preflight instead performs actual `--cached --3way` application in a disposable copied Git index,
then checks the exit status. Only after current-fact revalidation is target `--index` application used.
The temporary preflight may create unreachable Git objects, but not target files/index/refs.

## Increment C3 — native current-fact gate

Implement `NativeRecoveryFactsVerifier(config, environment).validate(plan)` and
`inspect(plan) -> NativeRecoveryFacts`. Resolve the original source via C1, then load the exact
already-persisted target preparation/profile/runtime binding. Re-discover current target profile,
recompile rules using the SAME company-context/hard-rule builder as the production Host, and require
exact target HEAD, clean logical checkout and source-base ancestry. No prepare/registry/DDL/store writes.
Permissions/denies must equal original Coder policy in this bounded version; narrowing or widening
requires another explicit policy design, not guessed glob containment. Validate the captured source
using the configured project's Git manager, not a caller-provided path authority.

NativeRecoveryFacts contains original approved documents plus target preparation, profile and baseline
in memory. It is not a new Product approval or dispatch permission. Existing RecoveryAuthorizationService
uses this concrete gate before proposal/decision/execution. A human approves exact new preparation and
base in RecoveryPlan; semantic reuse of an old design is never inferred from a clean Git merge.

Good: offline failed native Coder, commit a newer clean base, prepare it through normal Host, propose/
authorize via fake trusted human, then reopen/revalidate with zero model calls and zero writes.
Base: same base/preparation. Bad: stale HEAD/profile/company knowledge, dirty logical checkout, invalid
source/capture, wrong company/binding/preparation, policy drift. Tests must preserve source bytes and
business revisions. Refactor shared production rule construction without changing rule digests.
CLI, upstream carry-forward persistence and fresh dispatch/Task/seed admission remain separate work.

Add an in-process `AuthorizedRecoveryTaskBuilder.build(plan_sha256) -> RecoveryTaskDraft` using
the existing authorization execution gate and concrete current facts. The draft holds a separately
rebound ProjectRequest (same product request identity, new preparation/time) and a NEW Task with
recovery-of metadata. Original request/Product/approval/Design/Plan are not modified or reapproved.
Reuse `derive_delivery_task`, preserve original constraints/attempt budget, and derive Task ID from
the approved recovery plan. Draft is not persisted/dispatched and cannot enter existing native
request stores by overwriting the original revision. A future atomic receipt must seal this exact
draft before dispatch. Tests require missing approval rejection, deterministic replay, unchanged
approved document digests, new Task/base with attempts zero, and current drift rejection.

## Increment D1 — durable authorized Task record

`RecoveryTaskRecord` seals exact plan/authorization digests, rebound Request and NEW Task in the scoped
FileRecoveryStore. `RecoveryTaskSealingService.seal(plan_sha256)` rebuilds through current authorization,
publishes one immutable record and replays exact content. `require_current(plan_sha256)` must rebuild
and compare the complete record before any future execution. Raw storage integrity is not authority.
No resource leases or dispatch, no Task DB write or worktree seed is added in D1. This is the durable
carry-forward prerequisite, not a completed execution receipt.

Validate NEW/attempts0, new Task/base/project/request identity and all recovery metadata against the
stored approved plan/authorization; bound size, secret rejection, no-follow/exclusive existing store
rules apply. Good: real current-facts fixture seals/reopens without changing original history. Base:
exact receipt read/replay. Bad: changed content, decision, Task identity, secret, file tamper or current
drift. Wire schema is separate `recovery-task-record.schema.json`; existing plan/auth schema unchanged.

## Execution integration

Distinct RecoveryDispatchRecord avoids fictional Planner READY revisions. MySQL global reservation
lock + original Product fence revalidate sealed current facts and compute fresh serial allocation.
Native dispatch remains strict; general role worktree/runtime consumers accept a typed allocation
union. Original Task/Request/parent are not rewritten. Shared production runtime method accepts
approved documents with the new Task and prepared profile; no second orchestrator implementation.

NativeRecoveryEntry exposes propose/approve/execute; CLI inspect can read Task via read-only SQL
without initializing Team Host. One private nonblocking scope lock excludes duplicate recovery
executors. Seed receipt atomically binds approved plan/dispatch/actual target capture; Codex admission
checks exact request/context/capture and seals invocation before provider launch. Ambiguous process
loss after this point fails closed; no silent second call or terminal reset. Ordinary dirty admission
is unchanged. Old joint-approved context is restored as required source, preserving prefix semantics.

Wire schema: recovery-execution.schema.json for dispatch, seed, invocation. Source models and stores
remain trusted organization infrastructure, not a sandbox against arbitrary filesystem/DB writers.
Recovery does not silently resume the terminal parent or perform multi-repository integration adoption.
New recovery evaluation events persist but are excluded from fresh-demand ADR to avoid double counting.
