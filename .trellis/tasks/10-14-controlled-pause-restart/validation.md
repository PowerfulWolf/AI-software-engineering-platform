# Validation and operations

Base: `4863eb49c038b4b271607ede314ffdad78ffc73b`; origin/main independently fetched and equal before integration.
Implementation is in the isolated `codex/controlled-pause-restart` worktree.

## Validation

- Ruff `check src tests` plus schema scripts passed; all 69 changed Python files format-check passed.
- Strict mypy src + changed maintenance/transport/inspection/baseline SQL tests: 381 files, clean.
- Full test-tree mypy has preexisting unrelated failures; no runtime change depends on those tests.
- Console lifecycle/inspection/API/epoch regression: 137 passed (`/tmp/ase-epoch-full-final.log`).
- Last maintenance depth/phase/security regression: 76 passed (`/tmp/ase-epoch-final3.log`).
- Contracts, fresh schema generation, real-Git baseline/reservation/invocation and fallback: 91 passed
  (`/tmp/ase-pause-contract-finish.log`).
- Isolated MySQL baseline pause suite: 35 passed; its three new fresh-claim cases subsequently 3 passed
  (`/tmp/ase-samebase-mysql-final.log`, `/tmp/ase-samebase-mysql-claim3.log`). Test-only field errors repaired.
- Prior real-session/native/Responses/worker pause suites passed; logs documented in implementation context.
- Independent Standards and Spec reviews performed in separate read-only agents. All code findings repaired;
  final wording about the 128-node maintenance reader bound corrected.

## 存量数据处置

No SQL migration or historical Task/Run/Artifact/verdict/approval rewrite. Original K1 is preserved.
Online old Host ordinary stop refuses OWNED_PROCESSES/UNCONFIRMED despite no active Operations. Old
in-memory reader has the already-fixed claim parser defect; disk update cannot repair the live object.
Deploy through the trusted local exact-identity fault-retirement channel, keeping REFUSED/UNKNOWN
historical facts. Repeated maintenance now archives the exact predecessor controls and completion tree,
blocks startup during partial phases and requires new inspection completion and normal admission.
Production action receipts and online verification are recorded separately after execution.

## Rollback / limits

No automatic timeout/provider retry/refund/verdict; outstanding synchronous HTTP waits for real return.
Unverified session/EOF/final save still refuses READY. Coder pause requires exact approved baseline,
including same-base outcome proof; old continuation permissions are not expanded.
Rollback must first use controlled stop and retain a reader for additive SERVICE_PAUSED/service_pause
records and the new maintenance epoch plan. A pending epoch is completed only by retrying its exact
plan; old marker/admission must never be manually restored.
