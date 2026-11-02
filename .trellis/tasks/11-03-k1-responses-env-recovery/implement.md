# Implementation evidence

Platform base `cb7bc78cd0d4c82ac621552749a1960f030a69d1`; development branch `codex/k1-responses-env-recovery`. The machine role-tool boundary now rejects every `uv` command except exact `uv --version` before the executor runs. The Responses Coder prompt points to existing tooling and honest `NOT_RUN` checks. The terminal read-only recovery path has a distinct v3 synchronous Responses completion kind for the exact sealed workspace-policy failure. It retains the lawful Git capture, separately records newly created ignored `.venv/` metadata, requires clean `coder_reapply`, and leaves the failed Task, Run, queue, route and workspace untouched. v1 native stop and v2 clean refusal retain their wire forms.

## Production stock, read-only

`/private/tmp/k1_responses_workspace_preflight.py` was run with the platform environment and the current K1 source. `NativeRecoverySourceReader` and `read_terminal_workspace_snapshot` passed the existing Task lock and complete two-read source/SQL/Git/inventory audit. Exact Task `task_recovery_7d49714ebf1ac1659e658b1017e47cd5` is BLOCKED; failed Run `run_97d0ae3e56704250bd7622d727d8ccd6` has no native stop. Legal current capture SHA `b45d8a9f239e8387799cb863c89a551361f691eaa56e3d279b1ad92feb0c1b42` contains a 14,863-character patch for exactly:

- `tests/learning_collection/test_delivery_contract.py`
- `tests/learning_collection/test_existing_data_rollback.py`
- `tests/learning_collection/test_schema_contract.py`

The proposed v3 snapshot SHA is `07b63bb7324112baf6b1b768f7bbf6ba5125c8523a54756bd191fc1808e2ff7c`; start inventory SHA `5b2f967d1848d3e8f7e45b1c852308b22a0059fef4a906a1dc6aa22de0807182`, current inventory SHA `3bf7d779bf121d5707ff3e19900d2fc544a20c398d63b924fa0506194d7222bd`. There are 18 new, wholly ignored `.venv/` entries, never recovery inputs. The inherited-input reader found two authenticated ancestors: the original 72,535-byte patch SHA `5248dc9a31a46ea17d966cd69803787b44b17df5ace27955dc609ec5a81bcf29` and an empty patch SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. No production Plan, approval or DB mutation was made by this preflight.

## Verification

- Red tool test before guard: four environment commands reached the executor. Green after guard: 13 role/command cases passed, including Coder, QA and Reviewer.
- Pure workspace snapshot and Plan v3 positive/negative cases; regenerated static Schema matches generated snapshot and Plan guards byte-for-byte and is idempotent.
- Isolated MySQL public fixture: historical Responses failure → public Continue → exact independent approval → new Coder → independent QA and Reviewer passed for v3 (264.76 s). Existing v2 clean-refusal variant passed (259.98 s).
- Focused Responses/recovery/tool suite: 187 passed, one unrelated ownership test excluded. Recovery and Schema suite: 192 passed.
- Ruff and strict targeted Mypy passed. One existing OS process-ownership test, `test_real_command_uncertain_stop_is_not_converted_to_tool_rejection`, is nondeterministic in this environment: sometimes command stop completes before its injected `killpg` fault, and sometimes the existing owned-session failure has a different message. It is outside the changed role-tool path and requires separate test-harness repair; no production result is inferred from it.

## Pending release

Run final quality checks, commit and push the reviewed patch, then stop/fast-forward/start the platform service under the controlled restart script. Fast-forward only the clean registered K1 repository. Re-run the exact read-only preflight against the released version, inspect the public proposed Plan and scope/patch/target SHA, then submit one approval. Continue until actual Responses Coder, QA and Reviewer finish. Keep K1 ProductSpec, Design, Plan and prior candidate frozen. Do not replay either old Task or alter historical records. Rollback restores the old platform binary; an issued v3 Plan must not execute under that old reader.
