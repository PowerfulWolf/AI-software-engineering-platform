# Design

## Project context

The Requirements context band owns both Project selection and creation:

```text
Project identity and explanation
  -> searchable Project picker
  -> right-aligned new-Project action and modal form
  -> Requirement master/detail workspace
```

The creator remains a typed `POST /api/v1/admin/projects` action and is shown only when the current
Team is controllable. Requirement creation uses the same shared modal shell. The master column holds
top-level Requirements grouped by lifecycle state; Repository Tasks remain delivery detail.

The new-Requirement action is rendered beside the selected Project's Requirement count. The global
page header keeps only refresh because creating a Requirement is Project-scoped work.

## Spec editor

The form is rendered as a normal panel instead of a collapsed `details` element. The stable
`spec_key` is an internal identity: each selected Markdown/TXT file derives a key and title from its
filename and becomes an independent Spec. Common role, stage, Repository, path and verification
fields apply to the batch. A derived-key collision pauses for explicit new-version confirmation.
Card-level update opens the current body and applicability in a modal, reuses the existing key and
creates the next immutable version. A new version remains inactive until explicit activation.

Background document import follows the same maintenance-page rule and stays expanded. It has no
maintenance-mode selector: a new upload is always a multi-file import, and an exact filename match
requires explicit replacement-risk confirmation. Card-level update reads the integrity-checked
normalized Markdown through a scope-owned GET endpoint and opens it in a modal. Auto-refresh does
not rebuild an open modal or discard unsaved input.

## Update and retirement

Background edit publishes the submitted Markdown as a new content-addressed document, inherits the
old document's selection state and adds the old identity to a digest-bound retirement record.
Logical Spec deletion first removes its active reference and then retires its stable key.

`retirement.json` is current-library state, not destructive erasure. List/context APIs exclude
retired entries, while immutable `documents/` records remain available to already-bound deliveries.
Re-importing the same document or publishing the same Spec key restores it to the current library.
Every UI delete action requires an explicit confirmation modal.

Roles and stages use a reusable `details`-based multi-select. Its summary shows the current selection,
and its menu contains native checkboxes. Submission reads values in the declared option order and
rejects an empty selection before calling the API.

## Optional verification contract

`verification` remains a required wire field so canonical records and digests stay structurally
stable, but the value may be the empty string. Good: a concrete human verification description.
Base: empty string when the team has not defined verification yet. Bad: more than 8,000 characters.
