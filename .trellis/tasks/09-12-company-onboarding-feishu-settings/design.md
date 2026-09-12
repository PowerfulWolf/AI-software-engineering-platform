# Design: company administration, local documents and settings

## Decisions

1. Keep the existing trusted loopback Web Console and add a sibling typed administration boundary;
   read projections remain read-only and Delivery commands still flow through `ProjectConsole`.
2. Company manifests remain immutable identities. Creating a Company calls the existing atomic
   `CompanyWorkspace.initialize`; switching the configured active Company writes a validated
   production configuration and requires Host restart.
3. Store imported knowledge beneath
   `companies/<company_id>/knowledge/documents/<document_id>/`. Each content-addressed directory owns
   an immutable manifest, the original source and normalized `content.md`. Configuration selects only
   normalized relative paths; existing context digest/drift guards remain authoritative.
4. Extract UTF-8 Markdown/TXT directly, PDF with `pypdf`, and DOCX with `python-docx`. Reject encrypted,
   unreadable, empty, oversized or unsupported inputs. Do not call a model or invent a summary.
5. Settings persist through the existing secret-free production config file using atomic replace.
   GET responses expose whether referenced environment secrets are available, never their values.
   Platform root, active Company, MySQL binding and port are restart-bound; other fields are persisted
   consistently rather than mutating an already-constructed Host.
6. Preserve the existing production configuration and CLI compatibility. Administration is optional
   in the transport seam so existing unit fixtures and the read-only team server stay valid.

## API surface

- `GET /api/v1/admin/companies`
- `POST /api/v1/admin/companies`
- `GET /api/v1/admin/companies/{company_id}/knowledge`
- `POST /api/v1/admin/companies/{company_id}/knowledge?filename=...`
- `GET /api/v1/admin/settings`
- `PUT /api/v1/admin/settings`

All mutation routes require same-origin loopback requests, typed validation and bounded bodies.
Document upload uses the raw request body rather than multipart, avoiding an ambient temporary upload
store and an otherwise unnecessary multipart dependency.

## User flow

1. Open Settings, create a Company, select it as the active Company and save.
2. Restart the local Console when the page reports restart-required configuration.
3. Open Knowledge, upload documents and select the normalized records in Settings.
4. Restart before starting new work so the active Host is bound to the exact selected knowledge.
5. Existing approved Deliveries remain pinned and fail closed on knowledge/configuration drift.

## Safety and failure behavior

- No arbitrary server-side paths are accepted for import; only browser-uploaded bytes and a sanitized
  basename cross the boundary.
- Source and normalized content are written to a hidden staging directory, fsynced, validated, then
  renamed once. Exact duplicate content replays idempotently.
- Browser errors do not echo document text, file-system paths, DSNs, API keys or tracebacks.
- Configuration writes never contain DSN/API-key values; only validated environment-variable names.
- Imported content is untrusted context and retains the existing company-knowledge priority.

## Verification

- Company catalog/create isolation and immutable replay.
- Markdown/TXT/PDF/DOCX extraction, duplicate import, traversal, symlink, empty and size rejection.
- Settings round-trip, validation, secret-status metadata and atomic write.
- HTTP Host/Origin/content-type/body limits and safe error envelopes.
- DOM tests for Company, Knowledge and Settings navigation/forms.
