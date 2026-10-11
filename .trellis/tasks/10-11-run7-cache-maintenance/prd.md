# K1 run7 preserved cache maintenance

Restore the ability to inventory the stopped K1 worktree without discarding source progress,
changing the FAILED outcome, or pretending the missing structured result was accepted.

Scope: exact Task `task_recovery_8ca06fa0aec236ab940597ad1482bfc8`, attempt7, revision8,
Run `run_a711050bf6384b73b588491472001fcd`. Only the four regular files under the root
`.mypy_cache` may be relocated to private sidecar audit storage. No source/test change,
Task/queue/database write, budget refund, new Requirement or Agent/verdict is authorized by
this maintenance plan. Subsequent delivery uses a separate exact public baseline decision.

Acceptance: complete bounded stable before inventory, exact cache digest/size, real original
completed stop and FAILED outcome, idle Task locks/fences, preserved HEAD/index/Git capture,
immutable plan/authority/HumanActionEvent, same-device no-overwrite rename, full retained cache
verification, and default 16MB after inventory differing only by those four cache paths.

Only incremental inventory/maintenance tests, Ruff and strict mypy. Rollback is an explicit
idle maintenance rename of the fully verified archive; never delete either side after an error.
