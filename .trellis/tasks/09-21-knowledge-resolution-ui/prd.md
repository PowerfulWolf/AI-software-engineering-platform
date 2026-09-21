# Approved knowledge resolution visibility

## Goal and confirmed facts

Make the next user action unambiguous after approving a knowledge answer. The existing
`knowledge/administration.py:list_gaps` returns immutable gaps without their resolutions;
`team_view/app.js:knowledgeGapCard` always creates a blank approval form. Approval only
changes the current DOM, and the Requirement checkpoint deliberately remains WAITING_HUMAN
until explicit resume. Thus reopening the page loses the approved presentation and shows
the old checkpoint instruction as a current blocker, despite a saved resolution.

## Requirements and acceptance

- R1: Project/Requirement-scoped queries join verified gaps to their exact approved
  resolutions. Preserve immutable gap, approval, checkpoint and historical Operation records.
- R2: Approved cards show the saved answer and source, no editable approval form. Pending
  current gaps retain one form and its draft. Historical gaps cannot request a new approval.
- R3: Refresh/reopen and background polling recover approval state even when the checkpoint
  hash has not changed. The current status and blocker guidance say approval is saved and
  explicit continuation is next; historical wait Operations must not contradict this state.
- R4: Approval never invokes delivery automatically. Continue uses the current checkpoint;
  subsequent new gaps remain actionable. Load failures cannot imply approval or completion.
- R5: Verify pending/approved/reopen/new-gap/corrupt-lineage cases using persisted fixtures
  and DOM tests, run lint/type checks and applicable contract tests, commit and push.

## Scope and rollback

Allowed: knowledge read projection, Console query, Team read model/schema, UI, related tests,
docs/spec and this task. No changes to approval authority, delivery execution, model calls,
stored business decisions or original production records. Reverting this patch rolls back
the presentation contract without a data migration. User operates the real Requirement.
