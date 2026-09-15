# Product Agent multi-turn requirement discussion

## Goal

Turn the Product stage from a one-shot form submission into a durable, bidirectional discussion in
which the user and Product Agent can clarify a Requirement over multiple turns before an exact
ProductSpec is presented for approval.

## What I already know

- Product discussion may require several rounds; one or two user messages are not sufficient for many
  real Requirements.
- Product Agent must be able to ask questions, and the user must be able to reply and continue the
  same discussion.
- Existing ProductSpec approval and downstream Designer/Planner/Delivery gates must remain intact.
- Text and pasted screenshots are already supported as user input.

## Confirmed behavior

- Every user and Agent turn must be durable and replayable after refresh or service restart.
- Product Agent questions are not ProductSpec approval candidates.
- Product Agent decides whether to ask another clarification question or produce a ProductSpec.
- Even after ProductSpec is ready, the user may continue the same discussion and request revisions;
  only explicit approval advances to Designer.

## Requirements (evolving)

- Show a chronological conversation containing both user and Product Agent messages.
- Allow repeated user replies, including pasted screenshots, until ProductSpec readiness.
- Show submitted screenshot metadata with the user turn without exposing sidecar file paths.
- Preserve exact dialogue/checkpoint lineage and prevent duplicate model calls on replay.
- Keep ProductSpec approval as a separate human action.
- Keep history and the composer in one discussion module while Product is unapproved. During
  Product processing the composer remains visible but disabled; interrupted processing resumes as
  “继续需求讨论”, not “继续交付”.

## Acceptance Criteria (evolving)

- [x] Product Agent can return clarification questions without advancing to approval.
- [x] User can answer and continue the same Product discussion for multiple turns.
- [x] Refresh/restart reconstructs the complete ordered conversation from durable facts.
- [x] ProductSpec-ready state still offers an explicit path to continue discussion and replace the
      unapproved candidate.
- [x] Only a validated ProductSpec candidate enables the approval action.
- [x] Stale/duplicate replies fail closed and do not create duplicate turns.
- [x] `PRODUCT_DISCOVERY` never replaces the discussion composer with a generic delivery action or
      inserts an internal detail-section divider.
- [x] With two or more Requirements, the entire selected card opens the exact Requirement detail by
      mouse or keyboard and remains selected across polling.

## Definition of Done

- Focused domain, persistence, Manager, transport and UI tests pass.
- Ruff, Mypy, JavaScript checks and code-spec synchronization pass.
- Full regression is ready for human execution.

## Out of Scope

- Realtime token streaming, voice discussion or multi-user collaborative chat.
- Allowing Product Agent to approve its own ProductSpec.
- Changing the downstream Designer → Planner → Coder → QA → Reviewer sequence.

## Technical Notes

- Applicable contracts: `.trellis/spec/core/production-team-host.md`, `web-console.md`,
  `multi-directory-delivery.md`, `contracts.md` and `delivery-recovery.md`.
- The joint Requirement runtime already persists `JointCheckpoint.dialogue`, accepts replies from
  `READY_FOR_DISCUSSION`, `WAITING_PRODUCT_REPLY` and `WAITING_PRODUCT_APPROVAL`, and lets Product
  Agent return either `clarify` or `ready`.
- The missing seam is the Team read model and browser presentation: `RequestView` currently omits
  dialogue, so Product Agent questions disappear after the operation completes.
