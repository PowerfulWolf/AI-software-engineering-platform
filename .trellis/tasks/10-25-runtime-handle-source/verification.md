# Verification of runtime-handle source capture repair

Maintenance baseline: `6bb73537c5bb7414564cc1b161bbabd32123118a`.
Guard-only manifest SHA-256: `d5fa1378987c59f2ede91e46ad7e88a4804adbc370fdac05ad1d597973a4e620`.
Independent reviewer: `/root/native_observation_design_check`; report SHA-256
`403ccb2170edfca4dd7ecdaebf91b014796b117ad493a5fa7f3684164ce9e4b5`.
No unresolved review findings. Local fake claim and literal/splat/factory
constructor negative tests were added red first and then fixed.

## Checks

Using the project Python with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src`:

- Independent `python -m pytest -q -p no:cacheprovider tests/context
  tests/git/test_runtime_token_capture.py tests/git/test_mutation_capture.py
  tests/orchestration/test_capture_reconciliation.py`: **511 passed, 11 skipped**.
- Exact baseline plus only the four guard files: **371 context tests and four
  real Git capture tests passed**, independent of unfinished mixed verification.
- Maintenance-worktree combined native-observation and guard verification:
  `python -m pytest -q -p no:cacheprovider
  tests/agents/test_native_observation_runner.py
  tests/agents/test_native_output_observation.py
  tests/manager/test_native_observation_deletion.py
  tests/manager/test_native_observation_purge_execution.py
  tests/orchestration/test_native_observation_store.py
  tests/context/test_runtime_token_references.py
  tests/git/test_runtime_token_capture.py
  tests/orchestration/test_capture_reconciliation.py`:
  **180 passed, 11 skipped in 68.54 seconds**.
- All 11 skips are existing v1 capability boundaries: ten ignored-retained-source
  cases and one multi-round-restoration case. No failed case was skipped as a fix.
- Ruff check, Ruff format check and strict Mypy passed on redaction.py and both
  new Python test modules. Ruff uses a private temporary cache because the
  sandbox cannot write this worktree cache; no code failure was suppressed.

## Actual original K1 readonly feedback loop

`ase-k1-eighth-capture-repro-readonly-20261025.py` reads the real Task in an
explicit readonly MySQL transaction, validates the original capture start/stop,
then invokes the actual full capture/coverage/reverification without persistence.
The final rerun passed all stages; Task revision remained 8, input source remained
`5547815464a04991f50a2e0532d6f2f13d8daa69`, 31 retained paths and 35 complete
captured paths were preserved. Full inventory SHA-256:
`81bd9617bf5b6d1a5c64a0133b47a7c0dc18fdd36695460f7bfbab7a4110d8a5`.
Capture SHA-256:
`e8bcd76bb9001d219914022e4e7b0213074efe3edad0edbda49f20a7801e67c2`.

## Stored data, rollout and rollback

No production SQL, K1 code, stop/outcome history, receipt or verdict was changed
by these checks. The existing rejected collection is preserved. Controlled stop,
reviewed maintenance fast-forward and official service start precede a fresh
public HANDLE. Only the HANDLE-produced current exact proof may authorize
same-Task continuation. No mixed executor is registered in this hotfix.

Before new capture persistence, rollback may return to the previous release while
idle. After new receipts exist, keep compatible full-byte readers; preserve those
receipts and UNKNOWN history rather than editing their bytes/hash for old code.
This maintenance verification does not constitute K1 candidate QA/Review.
