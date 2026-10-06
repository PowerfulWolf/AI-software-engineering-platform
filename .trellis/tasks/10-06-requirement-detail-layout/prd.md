# Requirement detail visual hierarchy

## Goal
After repairing memory retention, make the current stage, current blocker and user's next action easy to find. Separate full historical operations/repository deliveries from current facts and explain exact current/historical K1 blockers with user-operated steps.

## Scope / allowed paths
Team View app.js/style.css, owning DOM/browser tests and web-console/incremental-polling specs. Read-only public/frozen-fact inspection for diagnosis; no delivery submission, approval, continue, new requirement or baseline modification.

## Acceptance
- Compact consistent section spacing and typography; current status/blocker/action precede reference/history.
- Current product decisions remain visible and existing typed action gates unchanged.
- Full history, original diagnostics/IDs/timestamps and record links remain accessible in stable keyed disclosures.
- Historical next actions labeled as belonging to that operation, never today's guidance.
- Polling preserves disclosures, row/document DOM and active form drafts; mobile has no horizontal overflow.
- Incremental DOM and real Chrome checks pass, with actual layout inspection.
- Existing K1 cause explained from current verified facts; user gets exact UI steps and performs all delivery actions.

## Verification / rollback
No full tests, no durable-data migration. Run selected affected JS/Chrome contracts, inspect screenshots. Refresh compatible frontend assets. Roll back assets and refresh without changing Requirement, Task, Operation, approval or evidence. Memory repair09edc12 remains separately revertible.
