# Runtime settings and status design

## Data flow

```text
Settings form (write-only DSN/API key)
  -> typed UpdateSettingsRequest
  -> validate DSN / allowlisted route variable names
  -> atomic runtime.env write + atomic production config write
  -> restart_required
  -> service launcher sources runtime.env on restart
  -> ProductionConfig resolves the normal environment indirection

Status tab
  -> GET /api/v1/admin/status
  -> saved runtime variables over current process environment
  -> bounded MySQL ping + executable/knowledge/route inspection
  -> secret-free RuntimeStatusSnapshot
```

## Contracts

- `runtime.env` is always derived from the exact production-config directory; there is no independent
  path override that could bind credentials to the wrong configuration.
- The file contains only names referenced by `database.dsn_env` or Responses-route
  `api_key_env`. Values reject control characters and are POSIX single-quote encoded.
- Existing values are preserved when the browser submits no replacement. Unknown names fail before
  either file is published.
- MySQL validation reuses the store connection parser/adapter and closes the connection after a
  ping. Exceptions collapse to a safe availability result.
- Runtime-variable changes require restart. Saved values do not mutate the environment mapping or
  the already constructed Team Host.
- Status is a query and never prepares workspaces, changes Task state or starts an Agent.
- Missing configuration uses built-in defaults and a setup-only Console. Missing/unreachable MySQL
  does not block Settings/Status; an existing invalid configuration never falls back.

## Verification

- Runtime env round-trip, quote handling, allowlist rejection and no secret reflection.
- MySQL test success/failure through an injected probe.
- HTTP status and connection-test endpoints.
- Browser navigation, DSN/API-key writes, Status rendering and absence of secret text.
- Launcher default/explicit runtime-env loading.
