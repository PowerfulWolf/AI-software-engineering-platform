# Web Console layout hierarchy

## Goal

Reorganize every Web Console tab around its real ownership boundary so users can immediately tell
whether they are looking at Team, Project or platform facts. Preserve the current administration,
delivery and read-side contracts.

## Requirements

- Group the sidebar into Team, Project work, Knowledge assets and System navigation.
- Add a visible page context band for Team, Project and platform scopes.
- Keep the Team roster Team-owned; label the Project selector as a workload filter.
- Render Requirements as a master-detail workspace with Project actions, grouped work and delivery
  details.
- Render Knowledge as an ownership sidebar plus content workspace. Keep editors collapsed until the
  user explicitly opens them.
- Split Settings into Basic, MySQL and Model routing sections with one persistent save area.
- Render Status as a read-only readiness summary plus grouped runtime facts.
- Preserve all existing APIs, safe text rendering and serial delivery semantics.

## Acceptance Criteria

- [x] Every tab visibly states its ownership scope.
- [x] Project selection is presented as context on Requirements and only as a workload filter on Team.
- [x] Knowledge clearly separates Team and Project ownership before content type.
- [x] Requirements use a two-column list/detail layout on wide screens and stack on narrow screens.
- [x] Knowledge and Settings use stable left navigation with one focused content area.
- [x] Successful operation history does not dominate the Requirements page.
- [x] Existing browser actions remain available and focused DOM tests pass.

## Out of Scope

- Cross-Project workload aggregation.
- New backend APIs or schema changes.
- Changing delivery, approval, knowledge or settings persistence.
