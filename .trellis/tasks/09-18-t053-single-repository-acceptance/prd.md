# T053 — Single-repository acceptance

## Problem

The parent Requirement currently requires joint integration evidence even when its scope
contains one repository. A reviewed native candidate can therefore be sent back to Planner
and become blocked on a redundant integration command.

## Contract

- One-repository Requirements finish by verifying the retained native DONE checkpoint and
  its durable QA/Review evidence.
- The parent records an immutable acceptance proof bound to the exact candidate, child
  checkpoint, ProductSpec and complete acceptance-ID set.
- Existing `PLANNING + plan=null` recovery checkpoints reuse their approved historical plan
  only to reconstruct the read-only native runtime; they do not rerun an Agent or rewrite
  history.
- Multi-repository Requirements still require executable cross-repository integration checks
  and successful evidence for the whole candidate set.
- Missing, stale or ambiguous evidence fails closed.

## Verification

- Focused domain/service regressions cover single-repository completion, legacy recovery,
  idempotency and unchanged multi-repository validation.
- Team view presents retained single-repository acceptance as waiting for delivery
  finalization, not as Planner execution.
