# Runtime settings and status tab

## Goal

Make the local Web Console the practical configuration entry for production runtime variables. A
user can enter the complete MySQL DSN and enabled Responses-provider API keys in Settings, while a
separate Status tab explains the effective configuration and readiness of the local Team Host.

## Requirements

- Settings accepts a complete MySQL DSN such as
  `mysql+pymysql://user:password@127.0.0.1:3307/database`.
- Settings accepts the API-key value for each configured Responses route. Codex CLI routes continue
  to use their existing local login and do not expose a key field.
- Runtime values are persisted in a local `runtime.env` next to the selected production config;
  this v0.1 increment prioritizes local usability and does not add Keychain/Secret Service.
- GET responses and the rendered UI never echo a saved DSN or API-key value. An empty write field
  means “keep the existing value”.
- The service launcher loads `runtime.env` before starting `ase-console`, so normal restarts do not
  require repeated shell exports.
- A dedicated Status tab shows the config path, runtime-env path, restart requirement, MySQL
  configured/connectivity state, Codex executable readiness, Team knowledge counts and model-route
  credential readiness.
- MySQL connection can be tested from Settings before saving without changing the running Host.
- Only runtime variables referenced by the typed production config may be written. Test/developer
  variables and arbitrary host environment injection are excluded.

## Acceptance Criteria

- [x] Saving a valid DSN writes a reloadable runtime environment file and never includes the value
      in the HTTP response.
- [x] An invalid or unreachable DSN returns a small stable error and is not reported as connected.
- [x] Restarting through `scripts/ase-console-service.sh` loads the saved runtime variables.
- [x] Status distinguishes configured/not configured and connected/unavailable without exposing
      credentials.
- [x] The Settings tab contains editable runtime values; read-only operational facts live in the
      Status tab.
- [x] Existing Project, knowledge, delivery and Team-view behavior remains compatible.
- [x] Focused administration, transport, UI, launcher, config and contract tests pass.

## Definition of Done

- Typed Python/API/UI contracts, focused tests, service script, README and executable Trellis specs
  agree.
- Ruff, formatting, strict Mypy, Node DOM tests and affected Python tests pass.
- Full regression is handed to the user, following the agreed incremental-test workflow.

## Decision (ADR-lite)

**Context**: Environment-only configuration forces users to export the DSN in every shell and mixes
read-only status into the Settings form. The product is still a trusted local single-user MVP.

**Decision**: Persist an allowlisted `runtime.env` beside the production config and load it from the
service launcher. Keep values write-only at the HTTP/UI boundary and add a separate Status view.

**Consequences**: This is plaintext local storage and is intentionally not the final security model.
The typed runtime-variable store is a replaceable seam for a later macOS Keychain/Linux Secret
Service adapter. A missing config or MySQL connection now starts a setup-only Console with visible
defaults; an existing invalid config still fails closed.

## Out of Scope

- Arbitrary environment-variable editing.
- `ASE_TEST_MYSQL_DSN`, `ASE_RUN_LIVE_TESTS`, `ASE_SERVICE_STATE_DIR`, `PATH` or locale settings.
- Remote access, RBAC, encrypted secret storage, Keychain and Secret Service.
- Hot-swapping the already constructed Team Host or database connection.

## Technical Notes

- Relevant modules: `config/production.py`, `web_console/administration.py`,
  `web_console/transport.py`, `web_console/host.py`, `team_view/`, and
  `scripts/ase-console-service.sh`.
- The repository does not contain the generic Trellis task helper scripts, so this task directory is
  maintained directly.
