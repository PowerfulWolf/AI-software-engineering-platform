# Model route kind identity and image capability

Goal: the available-model catalog and Agent policies distinguish Codex CLI and Responses routes
even when Provider, Model and Reasoning are identical; the image-input badge reflects the
effective per-route capability. CLIProxyAPI remains a Codex CLI connection option, not a model
execution type.

Scope: production config, typed workforce/dispatch/runtime/fallback contracts, Settings UI,
matching JSON Schemas and Trellis/docs. No provider protocol change, secret migration or Task
state rewrite. Work only in the affected `src/`, `schemas/`, `tests/`, `docs/` and `.trellis/`
paths. Use only incremental tests.

Acceptance:

1. Two routes with the same Provider/Model/Reasoning and different `kind` save, select and
   execute independently; an identical four-tuple is rejected in UI and backend.
2. New role policy, selection, Agent definition and delivery attempt persist the exact type.
   Old untyped facts resolve only when the frozen route set has one match; ambiguity fails closed.
3. Explicit `image_input=false` displays “仅文本” for Codex CLI; absent Codex CLI values display
   “默认可传图” and preserve the existing true runtime default. Responses still defaults false.
   Both types can be edited in Settings.
4. CLIProxyAPI is not added as a route type. Secrets are neither logged nor embedded.

Validation: focused Python config/roster/queue/fallback/runtime/dispatch tests, Settings Node
DOM tests, affected schema checks, Ruff, mypy and diff whitespace check. Rollback: revert this
commit; no database migration or existing fact mutation is required.
