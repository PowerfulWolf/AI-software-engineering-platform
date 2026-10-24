# Verification and existing data

Original defect reproduced before the fix with 16 failing cases: unsupported Codex provisional reports created candidates; generated Codex/Responses schema accepted v1.0; generic live/replay publication raised SchemaVersionError; current admission accepted historical unsupported outputs.

Final isolated maintenance-worktree validation (2026-10-25):

- Targeted adapters, generic current/replay output, immutable store, published JSON Schema contracts and three isolated MySQL Worker roles: **315 passed in 19.94s**. Log `/private/tmp/ase-version-target-green-20261025.log`.
- Strict mypy: **12 source/test files passed**. Log `/private/tmp/ase-version-target-mypy-20261025.log`.
- Ruff checks and formatting passed.
- Independent reviewer: **247 tests passed**, strict mypy for all 6 source files and Ruff passed; exact 6 source SHA equality checked between mirror and maintenance worktree. Report `/private/tmp/ase-artifact-version-admission-independent-review-20261025.json`, SHA `6448207aafd149aae699ec49f05e2b2bfde73e28e0103e721b58330c669176ec`. Reviewer inspected the final MySQL test; its sandbox refused the localhost connection before database mutation, so the independent run does not claim those three database tests. Final target review report `/private/tmp/ase-artifact-version-target-independent-review-20261025.json`, SHA `f4e6a42c647891a1d64012a01f9877d5f7b9819d88c52f69e8795af4e9fb2d43`.

The real MySQL checks prove policy-selected WAITING_DEPENDENCY/INVESTIGATE_EXECUTION, preserved Task role checkpoint, lease release, no retry refund, rejected output not published, and no new Agent call when the waiting delivery is invoked again. Test safety hooks verify the isolated test database before resetting test facts. No production SQL writes.

## 存量数据处置

K1 Task `task_recovery_3a4325237347c8caf434d94379cce745` still preserves its original source `5547815464a04991f50a2e0532d6f2f13d8daa69`. Run10 has an immutable SUCCEEDED v1.0 implementation output, a genuine completed stop and clean candidate `308bf36b7e225e875e5e84c1eb893fdd6e52f360`. This preventive fix does not rewrite the report, outcome, stop, Task or queue. Existing recovery gates correctly reject that combination; the original Requirement remains blocked until a separate exact candidate-rescue contract is implemented, reviewed and consumed through public APIs. Do not equate deployment of this fix with K1 recovery or completion.

Rollback: revert this maintenance commit before any later recovery consumption. No DDL. Preserve all old records, drafts and candidate references. The generated provider schemas constrain live output only; historical typed decoding and hashes remain compatible.
