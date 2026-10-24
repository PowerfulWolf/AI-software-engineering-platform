# Stable Darwin owned-session identity

Fix the reproduced rejection caused by comparing adjustable kern.boottime microseconds. New native observations must use the canonical hashed kern.bootsessionuuid. Preserve all historical proof bytes and strict rejection for unbridged legacy proofs. No process stop, verdict, Task, budget or K1 source is fabricated.

Initial allowlist: owned_sessions.py, tests/execution/test_owned_session_inspection.py, core/owned-session-stop.md and this task directory. Tests must prove clock drift no longer changes new boot identity; denied/malformed UUID never falls back to wall clock; foreign boot, live birth/SID and legacy mismatch still refuse. Existing K1 needs a separately verified historical stable-boot anchor and real lineage before a compatibility bridge can be implemented.

Rollback while idle, retaining compatible readers for newly published stop facts.


## Exact legacy continuity extension

Allowlisted implementation: `src/ai_software_engineer/manager/owned_session_boot_bridge.py`,
`manager/baseline_production.py`, `manager/knowledge_invocation_proof.py`,
`manager/production_backend.py` (baseline-service factory only),
`orchestration/capture_reconciliation.py`, `orchestration/continuation.py` (explicit optional
reader seam), and `tests/manager/test_owned_session_boot_bridge.py`.

The original task remains. Supplement only the boot identity of exact previously sealed
native receipts, using a prior approved stable-boot isolation anchor from this same Task
or its fully validated recovery ancestors. Fresh stable machine/session/account observations
must surround the unchanged original leader/birth/SID double scan. No new operator stop
statement, proof rewriting, process signalling, source update, verdict, SQL mutation,
transient refund or background automation is included. Exact PAUSE/RESUME authority remains
separate and mandatory. The minimum affected baseline paths are covered; other legacy
recovery/cleanup entry points retain their existing strict behavior.
