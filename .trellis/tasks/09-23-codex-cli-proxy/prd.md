# Explicit local proxy for Codex CLI routes

## Goal

Let the production platform run its Codex CLI routes through a locally managed
CLIProxyAPI-compatible Responses proxy without loading the operator's full Codex
configuration or requiring a direct ChatGPT CLI session. Proxy authentication
uses Codex's stored API-key credential in URL-only mode; the follow-up adds a
write-only managed-key mode without putting a key in argv or prompts.

## Follow-up: platform-managed proxy key

The operator also needs the same write-only API-key entry available for MySQL
and Responses routes. Add an optional, config-referenced proxy key environment
name and a password field on Model Routing. A key entered through Settings is
stored only in sibling `runtime.env` (0600), never in config JSON, a response,
an Operation, argv or a model prompt. Codex receives only this explicitly
referenced key in its process environment and uses provider `env_key`; it must
not expose that variable to model-invoked shell commands. Existing proxy URLs
without a managed key continue to use Codex's own saved login.

The operator-supplied key in the conversation is not an implementation fixture
or a value to copy into source. The operator should rotate it and enter the new
value in the write-only field after deployment.

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
- [ ] URL-only proxy configuration can use Codex's stored API key; a missing/revoked credential
  fails explicitly rather than silently changing providers.
- [ ] Focused Python and UI tests pass; no full test suite is run.
- [ ] Settings accepts, persists, reports configured status for, and replaces
  the proxy key without ever returning its value; clearing the proxy/mode prunes
  the managed secret from `runtime.env`.
- [ ] Both Codex CLI call paths use `env_key` only when the managed key is
  configured; they fail closed when its runtime value is missing and keep the
  key out of argv, diagnostics and model-invoked shell environments.

## Allowed paths / verification / rollback

Allowed: production config/schema, CLI adapter composition, Settings UI, focused
tests, `docs/production-setup.md`, relevant `.trellis/spec/` and this task record.
Verification: focused pytest, focused Node UI tests, Ruff/mypy on changed scope.
Rollback: revert the commit and leave the optional setting unset; no database
or Requirement migration is required.
