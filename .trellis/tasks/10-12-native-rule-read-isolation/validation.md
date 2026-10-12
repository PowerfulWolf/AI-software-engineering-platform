# Validation

## RED before source change

`PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/web_console/test_native_rule_read_isolation.py -k 'responsive and ConsoleOperationNotFound'`

Result: 1 FAILED / 4 deselected. The fixture Operation lookup exhausted its deadlock watchdog
with `Console read blocked its own HTTP release path`; the direct call originated at
`transport.py:native_rule_change`. The same loop could not run the heartbeat and release path
while the store lookup was held. The test has no wall-clock performance assertion.

## GREEN after source change

`PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/web_console/test_native_rule_read_isolation.py tests/web_console/test_native_rule_review.py`

Result: 7 PASS in 7.72s. The Event-held lookup remained unfinished while `/api/v1/console`
returned 200, then the explicit release yielded the unchanged fixed 409 error. Not-found,
conflict and I/O errors retained the same envelope without private diagnostics; invalid
identity/unavailable administration never reached the store. Existing complete before/after
rule, changed-manifest, unsafe-path and unchanged-file checks also passed.

`python -m ruff check --no-cache src/ai_software_engineer/web_console/transport.py tests/web_console/test_native_rule_read_isolation.py`

`python -m ruff format --check --no-cache src/ai_software_engineer/web_console/transport.py tests/web_console/test_native_rule_read_isolation.py`

`PYTHONPATH=src python -m mypy --cache-dir /tmp/ase-native-rule-read-mypy src/ai_software_engineer/web_console/transport.py tests/web_console/test_native_rule_read_isolation.py`

Result: Ruff/format PASS; mypy 2 files PASS; `git diff --check` PASS.
Commands used the existing main checkout's Python 3.12 virtualenv with this worktree's `src`.
Only existing Starlette deprecation warnings were emitted.

## Boundaries

All tests used isolated temporary fixtures; no browser, production service, SQL, K1 or restart
operation occurred. No migration is necessary and no persisted delivery data is rewritten.
This is a confirmed independent blocking bug, not an established root cause for the user's
reported Team read failure. Complete production rule inspection can still take time; moving
its lookup to a worker does not make the underlying store read faster or add a new timeout.
Rollback removes the narrow worker dispatch change while retaining all durable records.
