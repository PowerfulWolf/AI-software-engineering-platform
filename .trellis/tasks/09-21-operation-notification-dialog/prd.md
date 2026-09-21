# Operation notification dialog

## Goal and scope

Replace the persistent global Console Operation cards with one dismissible notification dialog.
Queued/running work must continue after dismissal. Terminal failures and successful operations that
require human action must provide a direct jump to the exact Requirement workspace. Project and
Knowledge page-level administration notices use the same dialog surface. Durable operation facts,
Requirement blocker sections, form validation, connection state and runtime readiness remain intact.

## Contracts

- `#operations` remains a compatibility/read boundary but never renders persistent cards.
- One operation status is announced once per browser using
  `operation_id + ACTIVE|FAILED|INTERRUPTED|ACTION_REQUIRED`; QUEUED -> RUNNING does not reopen it.
- A later terminal/action-required state for the same Operation is a new notice. Acknowledgement is
  bounded to 200 local keys and never mutates the durable Operation.
- Failures and human-action results with an exact Requirement target show “打开需求工作区”. Runtime
  setup/team mismatch notices link to Settings or Status. Pure progress notices have only “知道了”.
- Contextual facts remain where they are authoritative: blockers in Requirement detail, field errors
  beside their form, connection/readiness state in its page. Closing a dialog must not hide those facts.
- Modal content is created with `textContent`; no server text is interpreted as HTML.

## Acceptance and verification

- Submit continue: one modal, no page-height operation card, close does not cancel work or reopen on poll.
- QUEUED -> RUNNING: no second modal. FAILED or ACTION_REQUIRED: a new alert/dialog with exact safe
  message and a jump button; clicking it selects and scrolls to the exact Requirement.
- Operations read failure/runtime not ready: one dismissible dialog with an appropriate optional jump;
  recovery clears the condition so a future recurrence can be announced again.
- Page-level Project/Knowledge success or failure notices use the dialog; forms and drafts survive.
- Focused Node UI tests and format/diff checks pass. No service restart, database mutation or live model call.

## Existing data and rollback

No data repair or migration is required. Existing Operations remain immutable and queryable; only their
browser presentation changes. Reload the Console assets after deployment. Roll back the HTML/JS/CSS/spec
changes to restore the old presentation.
