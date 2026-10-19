# Producer verification

Checkout: `/tmp/ase-fix-legacy-ignored`.
Interpreter: `/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python`.
All pytest commands use `PYTHONPATH=/tmp/ase-fix-legacy-ignored/src:/tmp/ase-fix-legacy-ignored`;
Mypy uses `MYPYPATH=/tmp/ase-fix-legacy-ignored/src` so the editable root installation
cannot silently select old source.

## Red evidence

Original new chain regression: `1 failed in 0.90s`, with provider calls=0, preserved
Task/events/draft and released Lease, but `executions=0`, `evidence=()` and
`INVOCATION_UNRECORDED`. This established the producer dropped its positive refusal.

## Green evidence

- `python -m pytest -q --tb=short tests/knowledge/test_invocation_pause.py
  tests/manager/test_paused_knowledge_recovery.py`: **16 passed in 1.19s**.
  Fifteen producer cases exercise four actual guard entrances, pause grace/cancellation,
  typed replay, generic/legacy absence rejection, independent receipt/index loss,
  publication failure, owner loss, native admission-closed and actual posted HTTP mixed
  history; the chain case runs real preparation→failure router→WorkerLease wait→collector.
- `python -m pytest -q --tb=short tests/knowledge/test_invocation_native.py` outside sandbox
  under the user's existing temporary-subprocess test authorization: **35 passed in 12.01s**.
  The sandbox run could not capture owned process sessions and failed conservatively;
  no stop checks were disabled. The authorized rerun tests native completion, failures,
  local limits, receipt publication loss and no duplicate invocation.
- Ruff check and formatter pass for all producer source and focused test files.
- Strict Mypy initially passes the producer's four source/test files. An expanded
  eight-file check reaches a consumer role-narrowing error only; consumer owner notified.
  Root owns final integrated typecheck and independent review.

## Stored data disposition

Producer never upgrades historical `FAILED/SERVICE_PAUSED + executions=[]`, changes an old
outcome/intent, creates a fake admission or synthesizes an actual process stop. The new
optional field is omitted when None to retain old nested digest bytes and record keys.
Production K1 rescue and exact current/legacy isolation are separate root-owned work.

## Rollback

Retain immutable new receipt/outcome/index bytes. Revert producer and consumer as one
coordinated maintenance change at a verified stopped role boundary; old deployments must
not consume new proof types. No production operations were run by the producer agent.
