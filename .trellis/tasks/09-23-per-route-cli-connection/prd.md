# Per-route Codex CLI connection

Goal: operators can choose ordinary CLI or CLIProxyAPI independently for each Codex CLI model
route, see the choice in Model Routing, and distinguish the connection used by completed calls.

Scope: production config, role routing and frozen Run facts, Codex adapter composition, safe
call diagnostics, read-only Team View, Settings UI, JSON Schemas, Trellis/docs and focused tests.
Responses routes keep their own Endpoint/API Key and have no Codex connection mode. No secret
value is added to API responses, logs, route attempts or diagnostics.

Acceptance:

1. Two otherwise identical Codex CLI routes may coexist when one uses ordinary CLI and the other
   uses CLIProxyAPI; identical five-field identities are rejected. Agent primary/fallback selection
   and frozen delivery scope choose the exact connection.
2. Ordinary CLI never receives proxy overrides or proxy Key. CLIProxyAPI routes receive the
   configured loopback URL and optional write-only Key. Proxy mode without a URL fails closed.
3. The catalog, Agent choices and read-only runtime status show the connection per route; new
   completed structured calls and delivery route attempts record direct/proxy without URL/Key.
   Historical records lacking the field are labelled unknown, not guessed from current settings.
4. Configs saved before this change preserve semantics: an omitted route mode inherits the
   pre-existing global proxy URL if present, otherwise ordinary CLI. Existing immutable facts
   remain readable; ambiguous old references cannot select between two new modes.

Allowed paths: relevant `src/`, `schemas/`, `tests/`, `docs/` and `.trellis/` files only.
Verification: focused Python and Node contract tests, focused Settings browser test, Ruff, mypy,
schema checks and `git diff --check`; no full test suite or real provider call. Rollback point:
revert this commit and restart the Host; no database migration is planned.
