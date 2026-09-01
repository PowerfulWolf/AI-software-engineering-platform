# T007 Technical Design

## Confirmed Public Seams

| Module interface | Input | Output | Failure behavior |
|---|---|---|---|
| `ContextRouter.route` | declared `ContextSource` tuple + `AgentRole` | role-filtered, priority/URI ordered sources | duplicate IDs or invalid role metadata rejected |
| `ContextBuilder.build` | `Task`, role, attempt, optional candidate revision | typed `ContextBundle` | source, policy, redaction, revision, or budget error; no partial bundle |
| `ContextBundle.to_wire` | typed bundle | JSON-compatible manifest + redacted content | no raw secret or implicit message can enter the wire payload |

`ContextBuilder` is retained as a Protocol in `ports.py`; `FileContextBuilder` is the v0.1 local implementation. `ContextRouter` is pure and has no filesystem, Git, or model dependency.

## Source and Routing Rules

- Required generated sections: `policy`, `task`, `role`; optional `candidate` and project/organization file sources are explicitly declared.
- A source with empty `roles` applies to all roles; otherwise it is included only when the requested `AgentRole` is present.
- Ordering is `(priority, uri, source_id)` and is independent of caller insertion order. Policy priority is 0, Task 30, role 40, candidate 50, and declared evidence defaults to 100.
- Path sources contain only repository-relative POSIX paths and are read beneath the configured root through T006 `WorkspacePolicy`; direct content sources are already materialized data and are still redacted.
- `candidate_revision` becomes `source_revision` when provided; otherwise the Task `base_ref` is retained as the source reference. The builder does not resolve Git refs or invent a SHA.

## Manifest and Budget Algorithm

1. Validate Task, role, attempt, candidate revision, and source IDs.
2. Route generated and declared sources, read file contents, redact secrets, and compute candidate token counts using deterministic `ceil(len(text)/4)` estimation.
3. Sort sources by priority/URI/ID. Include complete sections while budget remains; optional sections that overflow are truncated to the remaining token budget or omitted when no token remains. Required policy/task/role overflow raises `ContextBudgetExceeded`.
4. Hash delivered redacted content with lower-case SHA-256, record section token counts and `truncated`, and record redaction kind/count without values.
5. Compute `context_id = "ctx_" + sha256(canonical_json(manifest_without_context_id_and_built_at))`.
6. Build the immutable `ContextBundle` with UTC `built_at`; no manifest is persisted or Agent run starts until this succeeds.

## Redaction Rules

Patterns cover OpenAI-style keys, AWS access keys, GitHub tokens, bearer tokens, PEM private-key blocks, and assignments whose key contains `password`, `secret`, `token`, or `api_key`. Replacement text is `[REDACTED:<kind>]`; pattern names and counts are safe audit metadata.

## Validation and Error Matrix

| Input or state | Result |
|---|---|
| duplicate/invalid source ID or role metadata | `ContextSourceError` |
| missing required file or unreadable/non-UTF-8 source | `ContextSourceNotFound` / `ContextSourceError` |
| path traversal, `.git`, absolute path, symlink escape, denied path | `ContextSourceDenied` |
| required section exceeds max input budget | `ContextBudgetExceeded` |
| optional section exceeds budget | deterministic truncation/omission, never over budget |
| secret pattern detected | redacted content + `ContextRedaction`, no failure |
| candidate revision contains control characters | `ContextSourceError` |

## Good / Base / Bad

- **Good**: identical inputs generate identical context ID/order/hashes; QA receives candidate revision and QA-only sources; a token is redacted before hashing and never appears in `to_wire()`.
- **Base**: an offline temporary project with declared Markdown sources builds a bundle under budget without Git, network, model SDK, or vector store.
- **Bad**: let a repository instruction override policy, concatenate all files without ordering/budget, hash/count secrets before redaction, route Reviewer-only evidence to Coder, or silently accept a required source that did not fit.

## Test Seams

1. `ContextRouter.route` with all-role and role-specific sources.
2. `FileContextBuilder.build` with temporary files, real T006 `WorkspacePolicy`, redaction, stable identity, budget, candidate revision, and failure cases.
3. Context JSON Schema positive/negative contract tests.

Tests do not mock the builder's internal filesystem or routing helpers.
