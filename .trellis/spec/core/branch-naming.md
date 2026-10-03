# Semantic delivery branch contract

## 1. Scope / Trigger

New production Product output, Task derivation, Git ownership, interrupted capture,
successor recovery/remediation and read-only candidate display. No branch migration,
automatic merge, permission expansion or historical digest rewrite.

## 2. Signatures

`BranchName`: `ai/(feature|bugfix)/<lowercase-kebab-business-slug>`, at most 240 characters.
`ProductDraft.branch_name`, `ProductSpec.branch_name`, `Task.branch_name` are typed optional
historical fields. New native and joint Product producers require the name on ready output.
`GitWorktreeManager(..., branch_names: Mapping[TaskId, BranchName | None])` receives a copy
of trusted frozen Task intent. `CapturedChanges.branch_name` preserves the actual branch.
`RecoveryPlan.target_branch_name` is bound to exact plan approval.
`NativeRecoveryEntry.propose(..., target_branch_name=None)` supports an explicit semantic
qualifier when a recovery name is occupied; CLI exposes `--target-branch-name`.

## 3. Contracts

- Product proposes feature for original functionality and bugfix for an independent defect.
  User approval binds the exact ProductSpec digest, including name. Do not classify using
  Task IDs, retry reason, inferred title keywords or the role currently doing the work.
- Joint child projection retains the approved name (repositories have separate ref namespaces).
  Only the trusted deterministic projection may read an approved legacy Product with no name.
- Same Task uses the existing Coder worktree/branch across QA rework, retry and restart.
  New successor Tasks retain source kind and append a meaningful purpose: `recovery`,
  `review-fixes`, or `prerequisite-repair`. Before appending, collapse any trailing generated
  purpose suffixes back to the stable Product business slug. This keeps repeated generations
  bounded while preserving the original scope; a business slug ending in a reserved purpose
  word is still treated as business text when it has no generated separator. Never add
  IDs/attempt counters, truncate into another name, rename a source branch or overwrite an
  occupied target.
- Branch name is not ownership. Always also check Task/path/role/registration/common-dir/HEAD.
  A caller-provided WorktreeRef cannot choose the manager's trusted branch mapping.
- Before removing a clean semantic Coder worktree, the Git manager atomically creates and
  fsyncs an empty manager-owned removal marker beside that worktree. Its filename contains
  SHA-256 of canonical JSON `{version: 1, repository, worktree, branch, spec}`; `spec` is
  `WorktreeSpec.to_wire()` with the observed full HEAD. The filename is
  `.<worktree-name>.removed-<sha256>`. This local ownership receipt is not a role Artifact or
  an execution approval. `restore_clean_coder` requires the exact regular, empty, non-symlink
  marker before recreating a missing semantic worktree, as well as the unchanged branch SHA.
  Missing/corrupt/copied cross-Task or cross-root markers fail with `WorktreeIdentityDrift`.
  Existing worktrees use the normal read-only identity checks. Legacy Task-scoped names keep
  their historical restoration behavior. Never fabricate a missing semantic marker from
  branch name/SHA alone; preserve the ref and require a separately approved new requirement.
- Capture retains the real name and existing hash algorithm. Native recovery compares it
  with the immutable source Task before capture authorization. Target branch must have the
  same kind, differ from source, and participate in the recovery plan digest.
- Missing fields are omitted even from ordinary model serialization. Historical unnamed
  Tasks retain `ai/<task-id>/attempt-N`; never guess their original feature/bugfix type or
  rewrite old Product/Task/dispatch/capture/approval bytes. QA/Reviewer stay detached.
- A name collision fails closed. Before initial approval, ask Product for a more specific
  name. For interrupted recovery, propose a new target name and approve the new exact plan.
  No reuse based only on a matching candidate SHA. Post-dispatch names are frozen; changing
  a sealed Task or moving the old ref is forbidden.
  There is no rename UI for a dispatched Task: use a separately approved requirement
  with a more specific business name; recovery alone has the explicit CLI override.

## 4. Validation & Error Matrix

| Input | Result |
|---|---|
| New ready Product without name | Invalid output, no downstream Task |
| Task/hash/attempt ref, traversal, uppercase, extra slash, invalid Git syntax | Validation rejects |
| Already occupied branch/path | WorktreeAlreadyExists; preserve both histories |
| WorktreeRef differs from trusted Task name | UnmanagedWorktree/identity drift |
| Clean semantic restoration has no exact removal marker | WorktreeIdentityDrift; no checkout |
| Recovery changes kind or reuses source name | Reject before approval/execution |
| Branch changed inside approved Product/Task/plan | Digest or immutable intent mismatch |
| Old record omits name | Byte/digest-compatible legacy behavior |

## 5. Good / Base / Bad Cases

Good: `ai/feature/account-trends` → same Task QA rework retains that name; a separately
approved interrupted recovery uses `ai/feature/account-trends-recovery`, and another
review-fix still uses `ai/feature/account-trends-review-fixes` rather than appending again.
Base: `ai/bugfix/project-switch` is an independent defect request.
Bad: `ai/task_continue_<hash>/attempt-1` for a new requirement, or switching feature to
bugfix merely because Reviewer rejected a candidate.

## 6. Tests Required

Real Git: both types, detached verifiers, clean restoration, dirty capture roundtrip,
restart, collision and forged ref refusal. Contracts: Product ready enforcement,
legacy exact dumps/digests, Product→Task projection, successor kind, schema parity,
target plan tamper and capture/source binding. Read model: exact named ref at candidate,
legacy fallback, unrelated same-SHA ref never mistaken for this Task.

Scripted Product fixtures must propose different business names for independent requirements
in the same repository. A shared constant tests a real collision; do not relax the Git guard
to make an unrelated delivery or baseline test pass. Capture fixtures that change branch
identity must rebuild `WorktreeChangeCapture` and serialize with
`CapturedChanges.from_capture(...)`, which recalculates its digest. Changing a sealed
`CapturedChanges` through `model_copy(update=...)` while keeping the old digest is tampering
and must remain rejected.

## 7. Wrong vs Correct

Wrong: infer branch from Task ID everywhere or trust `WorktreeRef.branch` as authorization.
Correct: approved Product→immutable Task→trusted Git composition; persist the actual capture
name and verify it against the native source before recovery. Keep execution IDs internal.
