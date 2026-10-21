# Verification and current K1 treatment

## Original failure and independent current scene observation

The original public Requirement remains delivery_multi_bb78e2316afca47d005384542f685174535b69db. Internal Task task_recovery_89eb5d5996f9f49490cec84e61998cae is now BLOCKED/revision3/attempt4/work_attempt2. A consistent SELECT-only snapshot at 03:33:55.146541Z found all four WorkItems CLOSED and claims RELEASED; the final claim ended 03:32:28.658469Z. Public summary separately reports BLOCKED/STOPPED/PERMISSION_DENIED with checkpoint ffe8bd78495496475c7465db68e6a59117f974a96471ad4d3d4c6e033282cad5. Operation operation_fd6484b97c806efa01db04fdc5ab4f5c is SUCCEEDED, which does not mean business delivery succeeded.

Exact main Run run_c9014385fa3c4dc6b0a7e4872876ad9e returned FAILED/POLICY_VIOLATION/transient=false without artifact. Outcome SHA91c4af230808e81f5ea8e66a89baadb1cc561b8fa5ba01ed9d0cec3ec425f6e0. Native stop is genuinely failed/rc1/output absent at 03:32:27.483088Z, stop SHA4da0c93d807a891adb0da0e225e3f966782bf1023a0c865edadcb7c5ebb61f8e, capture-stop SHAe8ae3086c3e9460a7b6ea7f2dda985624c3890b16322fb04c11a0111400b5a59. Owned-session-empty proof SHAf4359cb62cdb8988a92483dedb37698471c38b1482c4f30c608cfc9e4fe4eced binds the actual original leader94360. Final route SHAa8b062a7df65a6b8da2b365b48a1526ececbb2932d7abb6cbe91bb0acf3be8ac matches the final result. Provider cause remains UNKNOWN_EXIT; no raw provider log was read or historical outcome rewritten.

At 03:36:10Z, an independent read-only inventory comparison found 2974 start entries (SHA9685c170e6c0d40946897199fe2b085bd09f428dadaf6033d2245d2aa665bf2c) and 2978 current entries (SHAa08625bc4872767fc539f4ae96c4d41cec6d565129fdd6db15136d5bb4b5beec). Exactly four new files are .pytest_cache/.gitignore, CACHEDIR.TAG, README.md and v/cache/nodeids. Noncache difference0; HEAD remains d401eda, staged paths empty. The 21 existing dirty paths are retained seed input, not new accepted progress. The private failed-invocation semantic-index snapshot was not persisted, so this observation cannot fully replay the original comparison or establish the provider cause. It does expose the default cache ownership gap independently reproduced by a real regression.

## Prospective fix and verification

The implementation and test results will be recorded here after actual checks. No success is inferred from planning.

## 存量数据处置

Keep the original failure, stop, evaluation intervention, approvals, frozen budgets and worktree bytes intact. Same-Task stopped-failure/provider proofs correctly reject the final POLICY classification. No direct SQL migration, source edit, cache deletion, budget refund, Task reset or verdict synthesis is permitted.

Under the existing delegated authorization, public Continue was submitted solely to prepare a current terminal recovery proposal: operation_ffb9894f63243d889bcc350cd377cfb5. Its first response is QUEUED; this note does not claim completion or approval. Several subsequent readonly GET attempts were not executed because the automatic approval reviewer reported model capacity. After repair deployment, prepare a fresh exact plan if the target revision changes, independently inspect complete capture/ignored inventory/inherited patches and authority, and approve only that current plan. Retain the same public Requirement and use the ordinary internal recovery Task path. A candidate must still pass native independent QA and Review at the same SHA.

## Rollback

At verified idle service boundary, revert only this cache-isolation code/test/spec change and use the official controlled replacement script. Keep all published lifecycle/recovery records and compatible readers. Rolling back cannot erase old POLICY history or authorize replay.


## Actual red/green and focused quality checks

Before production changes, a real registered `ASE_PROJECT_PYTEST` subprocess executed its
focused test successfully, wrote its default workspace cache, and a fake native runner then
returned unknown rc1. The adapter regression failed: expected PROVIDER_UNAVAILABLE, actual
POLICY_VIOLATION (1 failed / 23 deselected). This reproduces the prospective default-cache
gap; it does not rewrite the historical provider cause or private snapshot.

After the minimal launcher/environment change, the following command completed **119 passed,
1 skipped in 69.93s** in the isolated maintenance checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/agents/test_coder_cache_isolation.py tests/agents/test_native_python_tooling.py tests/agents/test_codex_failed_continuation.py
```

The one skip is the existing opt-in real native sandbox probe in
`test_native_python_tooling.py:711`; no claim of live model or new OS sandbox acceptance is
made from that test. Cache suite24 cases are included in the119 total, not additional tests.
They execute actual pytest through both trusted launchers with inherited, reduced and hostile
child environments, project cache defaults, spaced private paths, unknown native failure,
explicit workspace overrides, role/no-tooling boundaries, fresh roots and cleanup. Existing
strict source/ignored-cache/index mutation rejection suites remain passing. Scoped Ruff
check/format, strict Mypy on the two changed Python files and git diff --check all passed.
No Schema or DB contract changed and no production data was used by these regressions.

The public proposal operation_ffb9894f63243d889bcc350cd377cfb5 subsequently completed
SUCCEEDED and sealed unapproved plan404e5698b2ce92a7b89be20bb6c6ae03bde408079a9f31bb547bdcff1a28e231.
Its independently inspectable facts preserve21 files, complete2978-entry scene snapshot
SHA459f253f6c29ec85c1b0e818271eb23b97cded9a23752ab5b06fb67f64a491c6 and the complete225678-byte
inherited patch SHA26710e71e0bf31c26b61b35daa749c4575671fbc7d9e2f4aff8f23c4a9c1cfb7. Its target
is stilld401eda and branch is recovery-5. It has not been approved or executed. A target
update after deployment requires a newly current exact proposal rather than reusing this
old approval opportunity.


## Independent read-only review

An independent reviewer found no actionable defects in the code/test/spec diff. It separately
passed scoped Ruff, Mypy and whitespace checks, and ran an additional temporary actual pytest
probe combining project addopts workspace-cache configuration, hostile child environment and a
private path containing spaces plus a single quote. The cache remained private, full source
inventory unchanged and private root cleaned after failure. The reviewer did not modify code,
merge or access production data. The119-pass suite above remains its own measured test total.
