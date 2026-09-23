# Explicit local proxy for Codex CLI routes

## Goal

Let the production platform run its Codex CLI routes through a locally managed
CLIProxyAPI-compatible Responses proxy without loading the operator's full Codex
configuration or requiring a direct ChatGPT CLI session. Proxy authentication
uses Codex's stored API-key credential, never a key in agent argv/environment.

## Scope

- Add one optional, secret-free local proxy base URL to ProductionConfig and Settings.
- Apply the same explicit provider overrides to upstream structured stages and
  Coder/QA/Reviewer Codex CLI runs; retain `--ignore-user-config` and sandbox flags.
- Keep the existing direct-login behavior when the URL is unset.
- Document restart, authentication, and existing-requirement recovery behavior.

## Acceptance criteria

- [ ] A loopback `http://127.0.0.1:8317/v1` URL survives typed config, schema,
  Settings save and restart boundaries.
- [ ] A configured CLI call selects only its explicit proxy provider; without
  configuration it uses the prior direct CLI command.
- [ ] Non-loopback HTTP, credentials, query/fragment, malformed and control-character
  URLs fail before any model call.
- [ ] No personal `config.toml` or proxy secret is read or copied into persisted facts.
- [ ] The local proxy can use Codex's stored API key; a missing/revoked credential
  fails explicitly rather than silently changing providers.
- [ ] Focused Python and UI tests pass; no full test suite is run.

## Allowed paths / verification / rollback

Allowed: production config/schema, CLI adapter composition, Settings UI, focused
tests, `docs/production-setup.md`, relevant `.trellis/spec/` and this task record.
Verification: focused pytest, focused Node UI tests, Ruff/mypy on changed scope.
Rollback: revert the commit and leave the optional setting unset; no database
or Requirement migration is required.
