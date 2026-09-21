# Normalize Trellis task and workspace records

## Goal

Keep the existing engineering history while making task metadata, the task index and workspace
policy consistent enough to maintain safely.

## Scope

- Document the canonical task directory and `task.json` format.
- Ensure every existing task directory has `id`, `title`, `status` and `phase` metadata.
- Register historical directories that had documents but no `task.json` without inferring their
  completion or verification status.
- List every task directory exactly once in the task index.
- Track the workspace policy while retaining ignored local journals.
- Preserve historical task paths and extension metadata.

## Non-goals

- Delete or move historical tasks or workspace journals.
- Reconstruct missing historical documents.
- Infer completed work, QA, review, deployment or user acceptance from indirect evidence.
- Add a new Trellis runtime, lifecycle script or application behavior.

## Acceptance criteria

- Every task directory has parseable JSON containing `id`, `title`, `status` and `phase`.
- Each directory appears in exactly one task-index status section and the summary counts match.
- Previously unclassified records use `legacy_unknown / needs_status_verification`.
- Existing task directories and local workspace journals are not removed or renamed.
- Documentation links to task paths remain valid and `git diff --check` passes.
