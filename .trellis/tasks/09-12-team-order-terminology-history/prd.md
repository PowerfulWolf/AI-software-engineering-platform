# Team order, user terminology and history cleanup

## Goal

Replace the overloaded Team/Project vocabulary with the agreed Team → Project → Requirement →
Repository model, render Team members in workflow order, preserve a merge-ready candidate branch after
independent QA and Review, and remove unfinished historical runtime data without damaging completed
deliveries.

## What I already know

- The requested display order is Manager → Product → Designer → Planner → Coder → QA →
  Reviewer.
- A successful delivery must retain a candidate commit and uniquely locatable candidate branch; the
  platform still does not merge the target main branch automatically.
- The pre-v0.2 persisted domain called the knowledge/work isolation boundary `Company` and called a
  multi-directory requirement container a `Requirement Project`.
- Runtime truth is split across MySQL and the external platform root. Deleting only browser rows or
  only filesystem journals would create inconsistent recovery facts.

## Assumptions (temporary)

- This is a complete domain correction, not only a browser vocabulary change. The hierarchy is
  `Platform → Team → Project → Requirement → one or more Repository/Directory scopes`.
- Agent Profiles, model policies, capacity and Team Knowledge belong to Team. Project owns Project
  Knowledge, a Repository catalog and Requirements.
- “Historical data” means durable runtime delivery/operation/worktree facts, not Git history, Team
  AgentProfiles, Project knowledge or production configuration.

## Remaining migration fact

- Resolve the exact set of completed Requirement IDs to retain and the exact runtime roots/database
  rows to remove before any destructive cleanup/migration.

## Requirements

- Sort team member cards by the explicit seven-role workflow order, with unknown/future roles stable
  after the known roles.
- Display `Manager Agent`, `Product Agent`, `Designer Agent`, `Planner Agent`, `Coder Agent`,
  `QA Agent`, `Reviewer Agent` in that order when present.
- Replace the current Company boundary with Team across domain types, configuration, schemas, APIs,
  storage paths and UI.
- Introduce Project below Team as the stable product/business context and knowledge boundary.
- Replace the current Requirement Project concept with Requirement below Project. A Requirement owns
  its participating Repository/Directory scopes and complete delivery facts.
- Rename Project Manager to Manager across role identity, services, contracts and UI because the role
  leads a Team and is not bound to one Project.
- A DONE requirement displays a candidate branch suitable for human merge after QA PASS and Reviewer
  APPROVE; no automatic merge/push is introduced.
- Delete unfinished historical runtime facts only after a read-only inventory proves which completed
  requirements are retained and a consistent cleanup plan covers MySQL plus sidecar state.

## Acceptance Criteria

- [x] A shuffled seven-member fixture renders cards in the agreed order.
- [x] Unknown roles render deterministically after the seven known roles.
- [x] Browser labels and versioned contracts use Team/Project/Requirement/Repository terminology and
      never expose Company, Requirement Project or Project Manager as active concepts.
- [x] DONE delivery UI describes the branch as merge-ready only when durable candidate branch facts
      exist.
- [ ] Cleanup inventory identifies retained DONE requirements and removable non-DONE facts before
      deletion.
- [x] Focused frontend/read-projection tests and formatting checks pass.

## Definition of Done

- Implementation and regression tests are complete.
- Relevant Web Console/live-view specs record the display ordering and vocabulary boundary.
- Destructive cleanup is separately evidenced and does not remove completed delivery facts.
- The user runs any requested full regression before commit/push.

## Out of Scope

- Automatically merging, pushing or deploying candidate branches.
- Deleting Git commit/branch history, retained completed Requirement evidence or configuration.

## Technical Notes

- Relevant code: `team_view/app.js`, `team_view/models.py`, `team_view/reader.py`, frontend fixtures,
  `web-console.md`, `live-team-view.md`.
- The repository does not contain the generic `.trellis/scripts/` helpers, so task artifacts are
  maintained directly.
