# Verification

- Initial URL-only change: focused pytest `118 passed`, Settings Playwright
  `2 passed`, Node Settings/readiness `25 passed` (commit `8b6ee10`).
- Managed-key follow-up: `.venv/bin/pytest -q -m 'not mysql'` on the six changed
  config/adapter/composition/administration modules: `134 passed, 3 deselected`,
  including 401/403 classification and Git environment isolation cases.
  No full suite ran; the three MySQL-marked integration cases require an
  unavailable local test database.
- Focused Settings Playwright: `2 passed` using the bundled Node dependencies;
  Chrome required an approved out-of-sandbox launch. It verifies password
  input and request-only key submission as well as layout.
- Ruff check and format check: pass on all thirteen changed Python files.
- Mypy: pass on seven changed production Python files.
- `node --check` and `git diff --check`: pass.
- Local listener: CLIProxyAPI is listening on TCP 8317. A minimal Codex CLI
  smoke using the explicit provider reached it, proving the URL/override path,
  but returned `401 Missing API key`; the currently cached ChatGPT refresh
  token is revoked. A successful live model response is pending operator
  API-key login and was not claimed.

## Remaining human validation

1. Rotate the credential disclosed in the conversation. In Settings → Model
   Routing → Codex CLI Connection, enter `http://127.0.0.1:8317/v1` and the
   newly issued proxy key. Save and apply the restart. The key was not entered
   by this implementation.
2. Resume the existing failed Requirement explicitly and verify a Codex CLI
   route succeeds via the proxy. The Status page checks only the executable
   and managed-key presence, not proxy health or authentication.

## Known risk / rollback / existing data

The proxy's model/structured-output support is not yet live-verified with an
authenticated request. Reverting this follow-up or clearing the optional URL
returns the historical direct CLI behavior after restart. `runtime.env` is
protected by `0600` but same-UID filesystem reads are not isolated from a
model-run process; use only in the documented trusted-local deployment.
No database repair is needed. Preserve existing Requirement/Operation evidence
and use the normal explicit Continue action; do not reset attempts or approvals.
