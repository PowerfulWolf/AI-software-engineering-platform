# Requirement edit and logical deletion

## Goal

Allow a user to correct a newly created Requirement's name and selected code directories, or remove
the Requirement from the active Project view, without mutating immutable delivery history.

## Requirements

- Show `编辑需求` and `删除需求` actions for a Requirement that is still
  `READY_FOR_DISCUSSION` and has no active browser operation.
- Edit in a modal prefilled with the current name and exact selected directory paths. Directory
  additions must continue to come only from the native directory chooser.
- An edit publishes a replacement Requirement and logically retires the original Requirement.
- Delete logically retires the Requirement after an explicit confirmation; it must not erase the
  checkpoint journal, attachments, or repository sidecars.
- A retired Requirement is excluded from Project counts and Team snapshots, and cannot be resumed,
  discussed, approved, edited, or deleted again.
- Deleting a Requirement also removes every native child Task derived from that Requirement from
  Agent queues and current Project projections; immutable sidecars remain audit evidence only.
- Closing a blocked Requirement is a reversible pause. It remains visible under a dedicated
  `已关闭` filter and can be explicitly restarted from the exact closed checkpoint.
- Queued close, restart and delete operations must not masquerade as active delivery work.
- Editing or deleting after Product discussion has started is rejected. Later-stage requirement
  changes require a new Requirement so approved Product/Design/Plan lineage is never reinterpreted.
- All mutations bind the exact currently displayed checkpoint digest and use durable Console
  Operations.

## Acceptance Criteria

- [x] A READY Requirement can be renamed and/or assigned a different 1–32 directory selection.
- [x] Successful edit selects the replacement Requirement and the old Requirement disappears.
- [x] Successful delete removes the Requirement from the active list after confirmation.
- [x] Refresh/restart preserves retirement and never physically deletes immutable records.
- [x] Stale checkpoint, unchanged edit, retired input, invalid roots, or non-READY stage fails closed.
- [x] A second active operation for the Requirement remains rejected.
- [x] Python models and public JSON Schemas remain aligned.
- [x] Closed Requirements are distinct from completed Requirements and can be restarted safely.
- [x] Deleted Requirements and all of their derived Agent queue entries disappear together.

## Definition of Done

- Focused domain/store, Manager, schema, reader and DOM tests pass.
- Ruff, strict Mypy, JavaScript syntax and diff checks pass.
- Relevant `.trellis/spec/` contracts are updated.
- Human runs the full regression before commit/push.

## Out of Scope

- Rewriting an already discussed or approved Requirement in place.
- Physical deletion of delivery history or source-code repositories.
- Restore/archive management UI or bulk Requirement deletion.

## Technical Notes

- `delivery_id` is derived from Team + Project + scope + title, so changing title/scope in place
  would break identity and idempotency.
- The existing checkpoint journal explicitly treats intake fields as immutable.
- Requirement retirement follows the existing Knowledge/Spec logical-retirement pattern: a
  Project-owned, digest-bound current index hides records while preserving immutable source files.
