# Design

## Contract

Add two Console intents:

```text
UPDATE_REQUIREMENT(project_id, delivery_id, expected_checkpoint_sha256,
                   name, repository_roots)
DELETE_REQUIREMENT(project_id, delivery_id, expected_checkpoint_sha256)
```

`JointDeliveryService.update_requirement` validates the exact original draft, creates or reopens the
content-addressed replacement through the normal intake path, then retires the original. The original
remains active if replacement intake raises before a valid checkpoint exists.

`JointDeliveryService.delete_requirement` validates the exact draft and records retirement. Both
operations accept only `READY_FOR_DISCUSSION` checkpoints with no dialogue, ProductSpec, approval,
design, plan, children, or integration facts.

## Persistent retirement index

`requirements/retirement.json` contains Project/Team lineage and sorted entries. Each entry binds the
retired Delivery ID, its exact checkpoint digest, timestamp, reason (`deleted` or `replaced`) and an
optional replacement Delivery ID. The record is digest-bound and written atomically under a process
lock. It is a current visibility index, not an erasure of historical checkpoints.

## Read model

The Team reader validates the retirement index, excludes retired joint Requirements, and excludes
them from Project Requirement counts. Direct delivery service access rejects retired IDs.

## UI

The Requirement summary action row contains Edit/Delete only for an idle READY draft. Edit reuses
the create modal layout with prefilled values and the native directory picker. Delete uses the shared
confirmation modal. A successful UPDATE Operation maps selection to its result Delivery ID; a
successful DELETE clears the removed selection.

## Validation matrix

| Case | Result |
|---|---|
| READY + exact digest + changed title/scope | replacement intake, then original retirement |
| READY + identical title/scope | reject; no retirement |
| WAITING/PRODUCT/DESIGN/DELIVERY/DONE | reject; no replacement or retirement |
| stale digest | reject before mutation |
| retirement index owner/digest/path drift | fail closed |
| deleted Requirement recreated with exact same input | normal create may restore the exact draft |

## Rollback

Remove the two intents and UI actions. Existing retirement files remain harmless historical data;
the reader must not ignore them unless an explicit migration/restore decision is made.
