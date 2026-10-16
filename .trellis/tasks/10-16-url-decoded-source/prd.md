# URL-decoded credential references in complete source captures

Goal: allow full legal Coder draft capture when existing Python source decodes a runtime
credential field with a statically proven standard-library URL decoder. Preserve complete
before/after source bytes, patches, SHA verification and all secret, policy and process gates.

Observed production failure: Run `run_411785d71edc4be4896a7f04d5f46b3b`, attempt 5 of
`task_recovery_622f711324450abfffedc2a8d696e2de`, stopped at its actual local window limit.
Public HANDLE reports `WORKSPACE_CAPTURE_REJECTED`. The read-only probe reaches real
`GitWorktreeManager.capture_mutations` and rejects the complete **base** body of
`src/ai_software_engineer/store/mysql_repository.py` (18,099 UTF-8 bytes, no NUL), at its
`password=unquote(parsed.password)` reference. Source scanning reports one secret_assignment.
The original accepted progress completes 01/02; attempts at 03/04 have no accepted result.

Allowed implementation paths: `src/ai_software_engineer/redaction.py`, relevant
`tests/context/` source-detection tests, `tests/git/test_mutation_capture.py`, existing core
source scanning spec and this task directory. No K1 checkout, production SQL, original
outcome/binding/artifact, runtime budgets, Schema or permissions changes.

Acceptance:

- A real Git capture of an unrelated change to a base containing the same URL decoder
  reference first reproduces the rejection, then captures and revalidates exact full bodies.
- Only statically proven standard-library decoding of a same-field runtime reference may
  receive a source-code exception. Unknown/literal calls, aliased/rebound/escaped imports,
  incomplete patch context, strings/comments and embedded fixed/strong credentials reject.
- Generic log/URI redaction remains conservative; no execution or import during inspection.
- Original live read-only capture passes with unchanged HEAD/index/source inventory. Only
  the public fact collector may later seal a receipt under its Task/queue fences.
- Independent review plus appropriate source/Git/continuation regressions and type/lint checks.

Rollback: controlled stop and code revert while preserving all immutable facts/readers.
After capture under the new rule, retain compatible source detection for any immutable full
body that legitimately uses the decoder; do not delete or rewrite evidence to fit old readers.

## 存量数据处置

No direct database repair. Keep Run5 timeout, real owned stop, unknown outcome and all draft
bytes. After independently reviewed deployment at an idle controlled boundary, obtain fresh
summary/checkpoint/disposition and use public HANDLE to recapture exact original facts, then
the precisely offered continuation operation. Verify new claim/Run and inherited accepted
01/02 plus full retained draft. Do not invent a result, restore a lease, refund an attempt or
declare 03/04 complete. Independent QA/Review remains mandatory for a candidate.
