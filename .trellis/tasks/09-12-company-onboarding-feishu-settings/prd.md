# Company onboarding, document knowledge, and settings console

## Goal

Make the local Web Console the complete platform administration entry: onboard and switch companies,
import local documents as company knowledge for the AI team to read, and manage every currently
supported operator configuration through a settings page.

## What I already know

- The platform currently has a single configured `company_id`; Company is the knowledge and work
  isolation boundary.
- Company knowledge is currently added as files under the Company sidecar and selected through
  `company_knowledge_paths` in a JSON config.
- The Web Console currently supports requirement creation, Product discussion/approval, delivery
  continuation, recovery approval, progress, and Candidate results.
- Browser commands use durable, typed, append-only ConsoleOperations and delegate state transitions
  to Project Manager application interfaces.
- Secrets must not be stored in the repository, Company sidecar, browser payload history, launchd
  plist, or systemd unit.

## Assumptions (temporary)

- v0.1 remains a trusted loopback, single-user console.
- v0.1 imports local Markdown, plain text, PDF and DOCX files, preserves the source document, extracts
  normalized Markdown/text and creates immutable company-knowledge records.
- “All configurable settings” means every field currently represented by `ProductionConfig`, while
  secret values use a secure indirection rather than being serialized into the public settings file.

## Requirements (evolving)

- Create a new Company from the Web Console and switch the active/read Company without mixing facts.
- Import local documents into the selected Company knowledge boundary and expose safe progress/errors.
- Preserve enough provenance for Agents and humans to trace normalized knowledge back to the exact
  uploaded source; do not silently summarize, truncate or invent content.
- Provide a settings page for platform root, Company identity, selected company knowledge, database
  settings, model routes, Codex executable, live-model switch, console port, and supported secrets.
- Preserve source filename, media type, source digest, normalized digest, import timestamp, original
  document and normalized output.
- Knowledge/config changes that invalidate prepared or approved work must create an explicit human
  drift gate; never silently reinterpret an existing Delivery.

## Acceptance Criteria (evolving)

- [x] A user can create/select a Company in the browser, restart the Host at the explicit boundary,
      refresh, and see only that Company's projects, knowledge, requests, and operations.
- [x] A user can upload Markdown, TXT, PDF or DOCX in the browser and observe a durable imported record
      or a stable safe error.
- [x] Import is content-addressed and idempotent, preserves the original file and never publishes a
      partial or oversized normalized document.
- [x] Normalized knowledge is reviewable and explicitly selected before it enters new preparation
      contexts.
- [x] Settings UI round-trips every supported non-secret ProductionConfig field with validation.
- [x] Secret settings never appear in GET responses, logs, operation artifacts, browser storage, or
      checked-in configuration.
- [x] Existing browser delivery flow remains compatible and full tests/lint/typecheck/build pass.
- [x] README and production docs describe browser-first company, knowledge, and settings workflows.

## Definition of Done

- Tests added for company isolation, document extractors, durable import/versioning, settings and
  secrets, browser flows, restart/idempotency, drift behavior, and safe errors.
- JSON Schemas and executable Trellis specs are synchronized.
- Focused tests, Ruff, formatting, strict Mypy, diff checks and offline build pass; the user runs the
  full regression before commit/push.

## Out of Scope (temporary)

- Remote multi-user access, RBAC/SSO and public hosting.
- Feishu Wiki/Docs and other remote knowledge connectors.
- AI-generated knowledge rewriting or silent summarization during import.
- Silent activation of changed knowledge for existing approved Deliveries.

## Technical Notes

- Relevant code: `company_workspace.py`, `config/production.py`, `web_console/`, `team_view/`,
  `project_manager/production_host.py`.
- Relevant specs: `company-workspace.md`, `production-team-host.md`, `web-console.md`,
  `context-routing.md`, `live-team-view.md`.
- The repository does not contain the Trellis task helper scripts referenced by generic skills, so
  this task directory is maintained directly.
