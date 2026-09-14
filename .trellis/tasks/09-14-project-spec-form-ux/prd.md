# Project context and Spec form usability

## Goal

Make Project/Requirement creation and knowledge maintenance feel like part of their owning
workspace, while preserving immutable historical records and explicit activation contracts.

## Requirements

- Place a new-Project action at the right side of the Requirements Project context band and open it
  in a focused modal.
- Replace flat Project chips with a searchable selector that remains usable with many Projects.
- Remove the disconnected Project creation panel from the Requirement list column.
- Place the new-Requirement action beside the Requirement count because it belongs to the selected
  Project's work list, not the global page header, and open its form in a focused modal.
- Use a compact Requirement master list and a delivery detail panel; hide the detail panel when the
  selected Project has no Requirements.
- Keep the new Spec form expanded instead of hiding it behind a details disclosure.
- Keep the background-knowledge import form expanded for the same maintenance workflow.
- Allow one background-knowledge import action to select and ingest multiple documents.
- Remove the background maintenance-mode selector. Same-name uploads must pause for an explicit
  replacement-risk confirmation, while card-level updates open the verified Markdown in a modal.
- Allow one Spec import action to select and ingest multiple Markdown/TXT documents.
- Present applicable roles and stages as accessible checkbox multi-select dropdowns.
- Allow the human-authored Spec verification description to be empty.
- Hide the internal Spec key from routine UI. New Specs derive it from the filename; updates reuse
  the existing key and publish a new immutable version.
- Let operators update or delete Team/Project background knowledge and Specs. Deletion removes an
  item from future context but retains immutable source records for historical delivery evidence.

## Acceptance Criteria

- [x] Project switching and the new-Project button share one visible context area.
- [x] Project switching supports search and does not render one permanent chip per Project.
- [x] The Requirement list begins with Requirement navigation, not Project administration.
- [x] New Requirement is shown beside the Requirement count only when a Project can be controlled.
- [x] Project and Requirement forms open as modal dialogs.
- [x] The Spec creation form is immediately visible.
- [x] The background-knowledge import form is immediately visible.
- [x] Background knowledge supports multi-file selection and reports batch progress.
- [x] Same-name background uploads require explicit replacement confirmation before the first write.
- [x] Existing background Markdown can be read through a verified endpoint and edited in a modal
      without auto-refresh discarding unsaved content.
- [x] Development Specs support multi-file Markdown/TXT import.
- [x] Roles and stages can be selected independently through multi-select dropdowns.
- [x] At least one role and one stage are required before submitting.
- [x] Empty verification text passes the UI, Pydantic and JSON Schema boundaries.
- [x] Background documents can be replaced with one new file while preserving and inheriting their
      current selection state.
- [x] Background documents and logical Specs can be deleted from Team or Project scope after an
      explicit confirmation, without removing historical files.
- [x] Updating a Spec reuses its hidden stable key and creates the next version.
- [x] Focused browser, Spec, administration and schema contract tests pass.
- [x] Human-run full regression passes.

## Out of Scope

- Removing immutable Spec revision history.
- Editing immutable historical records in place or automatically activating a new Spec version.
- Permanent erasure and garbage collection of retired historical records.
