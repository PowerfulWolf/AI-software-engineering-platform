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
