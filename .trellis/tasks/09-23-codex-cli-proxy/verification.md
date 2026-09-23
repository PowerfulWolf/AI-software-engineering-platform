# Verification

- Focused pytest: `118 passed` across config, Codex structured/delivery
  adapters, administration and production composition. No full suite ran.
- Focused Settings Playwright test: `2 passed` (Chrome required an
  out-of-sandbox launch); model-page alignment and submitted proxy URL checked.
- Node Settings/readiness tests: `25 passed`.
- Ruff check and format check: pass on changed Python files.
- Mypy: pass on six changed production Python files.
- `node --check`, `git diff --check`, task metadata validation: pass.
- Local listener: CLIProxyAPI is listening on TCP 8317. A minimal Codex CLI
  smoke using the explicit provider reached it, proving the URL/override path,
  but returned `401 Missing API key`; the currently cached ChatGPT refresh
  token is revoked. A successful live model response is pending operator
  API-key login and was not claimed.

## Remaining human validation

1. Obtain the proxy API key without pasting it into the platform or repository.
   In the same OS user and Codex credential environment as the Console, log
   out of the revoked ChatGPT CLI session and run
   `printenv CLIPROXY_API_KEY | codex login --with-api-key` with the key supplied
   securely in that shell. `codex login status` should report API-key login.
2. In Settings → Model routing → Codex CLI connection, enter
   `http://127.0.0.1:8317/v1`, save and apply the restart.
3. Resume the existing failed Requirement explicitly and verify a Codex CLI
   route succeeds via the proxy. The Status page checks only the executable,
   not proxy health.

## Known risk / rollback / existing data

The proxy's model/structured-output support is not yet live-verified with an
authenticated request. Reverting this commit or clearing the optional URL
returns the historical direct CLI behavior after restart. No database repair
is needed. Preserve existing Requirement/Operation evidence and use the
normal explicit Continue action; do not reset attempts or approvals.
