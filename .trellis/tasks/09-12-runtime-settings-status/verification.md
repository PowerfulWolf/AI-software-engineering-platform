# Verification

## Automated incremental checks

- `uv run ruff check` on the changed config/store/Web Console modules and focused tests: passed.
- `uv run ruff format --check` on the same scope: passed (20 files formatted).
- strict `uv run mypy` on config/store/Web Console: passed (12 source files).
- focused pytest for production defaults, runtime environment persistence, administration,
  transport and the service launcher: **45 passed**, with the two existing Starlette/httpx/anyio
  deprecation warnings.
- `node tests/team_view/ui.test.cjs`: passed.
- `sh -n scripts/ase-console-service.sh`: passed.
- `git diff --check`: passed.

## Manual/full regression handoff

Per the agreed workflow, the assistant did not run the full suite. Run it against a dedicated test
database, never the production delivery database:

```bash
ASE_TEST_MYSQL_DSN='mysql+pymysql://USER:PASSWORD@127.0.0.1:3307/TEST_DATABASE' \
  uv run pytest -q
```

After the full suite passes, restart the local Console and verify the first-run/configured paths in
the browser:

```bash
./scripts/ase-console-service.sh restart
```

1. Settings shows built-in defaults or the saved configuration.
2. A full MySQL DSN can be tested and saved without being echoed after save.
3. Status shows delivery runtime, live-model switch, MySQL, Codex, Team workspace, knowledge and
   model-route readiness.
4. A saved runtime value requires restart, then reports as effective.
