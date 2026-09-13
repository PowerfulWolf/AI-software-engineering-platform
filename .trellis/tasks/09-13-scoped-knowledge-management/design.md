# Scoped knowledge management design

## Data flow

```text
Knowledge page
  -> choose Team or selected Project scope
  -> GET/POST scope-bound immutable documents
  -> PUT scope-bound selected document IDs
  -> atomic knowledge/selection.json
  -> TeamHost resolves effective Team + Project selection per Project request
  -> cached Project runtime reused only while exact ContextSource tuple is unchanged
  -> Requirement preparation seals the resulting source lineage
```

## Persistent layout

```text
<platform_root>/team/knowledge/
├── documents/<document_id>/{source.*,content.md,manifest.json}
└── selection.json

<platform_root>/projects/<project_id>/knowledge/
├── documents/<document_id>/{source.*,content.md,manifest.json}
└── selection.json
```

Project document manifests bind both `team_id` and `project_id`. Selection records bind their scope,
owner identities and sorted normalized document paths with a canonical digest. Missing selection
records fall back to the existing `ProductionConfig` paths only for compatibility; a Web selection
write establishes the sidecar as authority.

## API contracts

```text
GET  /api/v1/admin/team/knowledge
POST /api/v1/admin/team/knowledge?filename=<basename>
PUT  /api/v1/admin/team/knowledge/selection

GET  /api/v1/admin/projects/<project_id>/knowledge
POST /api/v1/admin/projects/<project_id>/knowledge?filename=<basename>
PUT  /api/v1/admin/projects/<project_id>/knowledge/selection
```

Selection request payload:

```json
{"document_ids": ["knowledge_document_<32 hex>"]}
```

The response is the scope's secret-free document view list. Unknown document IDs, wrong Project
identity, unsafe uploads, tampered records and cross-scope selection fail before publication.

## Restart boundary

- Live/no restart: create Project, upload knowledge, change Team/Project knowledge selection.
- Restart: platform root/Team binding, database and runtime values, model routes, Codex executable,
  live execution and Console port.
- Existing `ProductionConfig.*_knowledge_paths` remain compatibility-only and still follow config
  restart semantics if changed outside the Web knowledge API.

## Failure behavior

- Selection writes are atomic and idempotent for the same selected paths.
- A missing selection file means no selected documents unless a compatible legacy config selection
  applies.
- Team selection is common; Project selection is resolved only from the explicitly requested
  Project.
- If selection/content changes during an operation, the existing preparation guard stops safely.
- The UI never guesses a Project when none is selected.

## Verification

- Team/Project immutable document and selection store unit tests.
- JSON Schema parity for Project document and selection records.
- Administration/transport tests for scoping, invalid identity and live selection.
- TeamHost tests for cache invalidation, cross-Project isolation and compatibility fallback.
- Browser DOM test for the two scopes, upload, immediate selection and no restart wording.
