# Requirement source baseline

## Goal

Allow multiple Requirements to progress independently from the exact code revision observed at
their creation time. Advancing the configured repository checkout for another completed delivery
must not invalidate an existing Requirement.

## Requirements

- Record and retain one immutable Git commit baseline for every selected Repository in a
  Requirement.
- Product, Designer and Planner must inspect the retained Requirement baseline, never the mutable
  configured checkout.
- Coder Tasks derived from a Requirement must start from that Requirement's retained commit.
- A later `master`/default-branch update must not block Product discussion, delivery continuation,
  QA, Review or joint integration for the older Requirement.
- Existing approved artifacts and checkpoints remain bound to their original source baseline.
- Missing, dirty or identity-drifted baseline worktrees fail closed without silently rebasing.
- The platform continues to return candidate commits only; merge conflict handling stays at the
  final human merge boundary.

## Acceptance criteria

- [ ] Two Requirements created from the same commit receive distinct retained baseline worktrees.
- [ ] Completing and merging the first Requirement into the configured checkout does not prevent
      the second Requirement from continuing.
- [ ] The second Requirement's Product client and Coder Task still use its original commit.
- [ ] Updating the configured checkout does not mutate the old Requirement journal or preparation.
- [ ] A missing or drifted retained baseline is rejected with a stable recovery-oriented error.
- [ ] Focused, contract, lint, type and full regression checks pass.

## Out of scope

- Automatic merge, push, deployment or automatic conflict resolution.
- Rebasing an in-progress Requirement onto a newer source revision.
- Sharing one mutable Product/Coder checkout across Requirements.
