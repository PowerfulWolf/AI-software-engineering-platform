# Incremental verification

All commands used the shared venv with `PYTHONPATH=src` from the isolated worktree; strict mypy
also used `MYPYPATH=src` and `/tmp/ase-cli-failure-classification-mypy`. No full tests, MySQL,
production API, real model, K1 operation or service restart was performed by this task.

| Check | Result |
| --- | --- |
| New background-auth classification cases before implementation | 7 failed, 2 passed, 3 deselected in 0.19s; false AUTHENTICATION_ERROR reproduced |
| Initial provider contract cases | 25 passed in 0.14s |
| Pure classification + actual Git preserved-progress fallback | 33 passed, 51 deselected in 3.85s |
| `test_codex_cli.py`, `test_codex_provider_contract.py`, `test_codex_failed_continuation.py` | 131 passed in 36.28s |
| Final provider contract after blank/JSON continuation and bounds cases | 31 passed in 0.15s |
| Independent-review JSON/indent/tail-boundary repros before correction | 6 failed, 31 deselected in 0.19s |
| Actual >1M subprocess truncation repros before typed capture fact | 4 failed, 47 deselected in 0.58s; seam false AUTH and lost-main-auth transient reproduced |
| Incomplete/over-bound main diagnostic before completeness gate | 4 failed, 40 deselected in 0.17s |
| Final focused provider + actual capture bounds | 50 passed, 45 deselected in 0.87s |
| Final `test_codex_cli.py`, `test_codex_provider_contract.py`, `test_codex_failed_continuation.py` | 156 passed in 45.48s |
| Additional exact-limit + actual observer binding focused checks | 5 passed, 47 deselected in 0.58s |
| Final scoped strict mypy | 5 source/test files passed |
| Scoped Ruff check/format + git diff check | Passed |

The earlier 131/31-case results preceded independent-review corrections. The final 156-case group
includes complete JSON parsing, actual capture truncation facts and incomplete diagnostic denial.
Final formatting changed no semantics. The later five-case subprocess-only group adds exact-limit
nontruncation and verifies the stop observer receives the same typed truncation fact; it changes no
production code. Existing adapter mutation/stop/fallback policy was not
modified. The actual Git fallback fixture adds eligible main transport failure despite background
auth, genuine nonretryable main auth and truncated/incomplete denial, each with/without new
mutations; it reopens durable route history and checks replay does not call either route again.
Actual subprocess tests preserve the fixed retained text length and real owned stop proof, verify
unknown truncation never grants fallback and keep genuine complete tail auth/rate categories.

Root independently reported two successful bounded health probes whose safe stderr shape included
timestamp-prefixed auth/MCP messages and no root Error/Fatal lines. This task neither read nor
saved their raw output. The previous failed run only retains digests; its first cause cannot be
reconstructed or relabeled from these successful probes.

Independent read-only reviewer `/root/recovery_read_cost/task_projection_reuse/sentinel_attack_review/completed_proof_tests`
rechecked the final diff against `05cb35b`, found no remaining blockers and approved submission.
The reviewer independently probed A–F, invalid/oversize JSON, typed truncated unknown and complete
tail auth; checked actual discard, publication before the observer, unchanged retained text/digests,
and unchanged EOF/stop/ownership gates. The reviewer did not rerun the 156-case group.

Root owns integration/deployment and the separate exact existing Task continuation gap; this task
does not make old AUTH transient or refund its budget.
