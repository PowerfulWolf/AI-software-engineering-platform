# Scoped Team and Project knowledge management

## Goal

Turn the current Team-only knowledge page into a scoped knowledge center. Users must be able to
distinguish durable Team-wide knowledge from knowledge owned by the currently selected Project,
and new Requirement preparation must consume the correct scope without requiring a Console restart
for ordinary knowledge administration.

## What I already know

- The browser currently exposes only `团队知识库` and always calls `/api/v1/admin/team/knowledge`.
- Team documents already use immutable content-addressed source/content/manifest records.
- `ProjectWorkspace` already owns `knowledge/` and can compile explicitly selected relative files.
- `ProductionConfig.project_knowledge_paths` is one global tuple and cannot represent several
  Projects correctly.
- Team Host currently combines Team and selected Project knowledge when composing a Project runtime.
- The user accepted a single knowledge center with `团队通用知识` and `当前 Project 知识` scopes.

## Requirements

- Rename the main navigation entry to `知识库` and provide two explicit scope controls.
- Team knowledge remains independent of the selected Project and applies to every new Requirement.
- Project knowledge follows the selected Project and applies only to new Requirements in that Project.
- Project document import uses the same bounded, immutable document contract as Team import.
- Knowledge enablement is stored in the owning Team or Project sidecar, not in one global Project
  selection inside `ProductionConfig`.
- Importing or changing knowledge selection does not require restarting the Console.
- Runtime binding settings—platform root, Team identity, MySQL, models/API keys, Codex executable,
  live execution and port—continue to require restart.
- Existing prepared/approved Requirements retain their recorded lineage and must never be silently
  reinterpreted under a new knowledge selection.

## Acceptance Criteria

- [ ] The browser clearly labels and switches between Team and current-Project knowledge.
- [ ] Team and Project APIs cannot read or write each other's document stores.
- [ ] Project endpoints require a valid Project identity from the configured Team.
- [ ] Team/Project selection changes are durable and visible without restart.
- [ ] A new Requirement receives current Team knowledge plus only its selected Project knowledge.
- [ ] Another Project never receives the first Project's knowledge.
- [ ] Existing Requirement lineage fails closed rather than adopting changed knowledge implicitly.
- [ ] Settings no longer presents Team/Project knowledge selection as restart-bound runtime config.
- [ ] Focused Python, UI, lint, type and contract tests pass; the user runs the full regression.

## Decision (ADR-lite)

**Context**: A singleton global `project_knowledge_paths` cannot model multiple Projects, and using
production configuration for knowledge content forces unnecessary Host restarts.

**Decision**: Store immutable documents and an atomic selected-document manifest in each owning
workspace. Resolve that selection when a Project runtime is requested, while preserving immutable
Requirement preparation lineage.

**Consequences**: Knowledge administration becomes a live control-plane operation. Runtime
composition needs an explicit selection revision/invalidation seam; changing knowledge affects new
preparation only and must not mutate an existing approval.

## Out of Scope

- Editing imported document contents in place; import a new immutable document instead.
- Automatic AI summarization, recursive directory import or Feishu integration.
- Cross-Project shared knowledge other than Team knowledge.
- Deleting historical document artifacts or rewriting existing Requirement facts.

## Technical Notes

- Relevant contracts: `.trellis/spec/core/team-workspace.md`, `web-console.md`,
  `production-team-host.md` and `python-runtime.md`.
- Relevant code: `knowledge_documents.py`, `team_workspace.py`, `project_workspace.py`,
  `manager/production_host.py`, `web_console/administration.py`, `web_console/transport.py` and
  `team_view/app.js`.
- The repository does not include generic `.trellis/scripts`; task records are maintained directly.
