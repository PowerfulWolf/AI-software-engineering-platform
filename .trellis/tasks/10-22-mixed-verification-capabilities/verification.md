# Stage 1 implementation draft — 2026-10-22

Base revision: `1ec4edd6f08bb09e8709f2c3e7519d734ee98f46`.
All source/test work is in the owned `/tmp/ase-mixed-verification-stage1-implementation-20261022`
mirror extracted from that exact Git revision. No main checkout, maintenance checkout,
production database/config, K1 Task/source/Plan/worktree, claims, budgets or verdicts were written.

## Implemented scope

Lossless typed effective-role partition and per-original-row prerequisite discovery; complete
whole-group and per-row digests; original-role preflight projection; truthful finite public
remedies; complete-group native/ordinary preparation and direct-binder no-start guard. Supported
homogeneous v1 discovery delegates unchanged. One exact parser definition is moved to the new
partition module and re-exported at its original import path. No aggregate/registry/browser/live
executor/deadline or new durable record shape is implemented. Only three existing preflight
detail enum values are added. Default hints are empty, never K1-specific routing.

Independent design review's medium role-projection issue is incorporated in `design.md`.
A separate helper agent only authored the offline summary trust demonstration test and then
read-reviewed partition/gate code. Its foreign/fallback and missing-fact observations led to
complete relational validation plus explicit tamper regressions. Final independent root review
has not yet occurred; this draft is not published or deployed.

## Actual validation

- Red: new partition test module initially failed collection with the missing production module.
- New partition and actual summary-spoof fixture: 16 passed before further relation cases.
- Initial old native/preparation test run under sandbox: 16 passed / 30 blocked by actual
  `OwnedProcessesUncertain` local process observation. No ownership boundary was weakened.
- Normal tool approval allowed the six-module focused suite to execute outside the sandbox:
  179 passed / 6 new-test failures. Four used the wrong existing marker enum (`WAIT_ENGINEERING`
  instead of `WAIT`), and two used a Coder unknown-execution fixture instead of a QA prerequisite
  fixture. The assertions/fixture were corrected; no runtime behavior was changed to satisfy them.
- Those exact six corrected tests then actually ran: **6 passed in 2.12s**. The public tests now
  use the original mixed Plan from before QA preparation, its real no-start marker, SQLite Task,
  original claim and queue facts; production accepted preflight feeds real inspect/handle and
  verifies receipt linkage, remedies, no retry/authority consumption, stable Task and idempotence.
- After final relation checks: **26 passed in 1.50s** in partition/summary/discovery-tamper/v1
  preservation/host-failure tests. They include omitted rows, changed fallback role/hash/detail,
  exact hint-level mismatch and the global 64-selector bound.
- Strict Mypy on all six changed production and six changed test modules: **success, 12 files**.
- Ruff check and format check: passed on the exact twelve Python paths.

Full affected-plus-adjacent command (historical Oct22 NOT_RUN; Oct24 execution below):

```text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src <trusted-python> -m pytest -q \
  tests/manager/test_native_verification_partition.py \
  tests/manager/test_native_verification_summary_trust.py \
  tests/manager/test_delivery_preflight.py tests/manager/test_native_verification.py \
  tests/manager/test_verifier_preparation.py tests/manager/test_delivery_wait.py \
  tests/planning/test_verification_feasibility.py tests/manager/test_verifier_capacity_input.py \
  tests/agents/test_verification_output_binding.py \
  tests/recovery/test_verification_output_composition.py --tb=short
```

Two normal automatic approval submissions for that final command returned
`Selected model is at capacity`: action **NOT_RUN**, not an OS rejection or unsafe determination.
No retry/bypass or fixture downgrade was used. These historical Oct22 NOT_RUN records remain;
normal approval allowed the actual Oct24 executions below. Integration remains at the existing
controlled idle boundary after independent review.

## 存量数据处置 / rollback

No migration or direct SQL modification is needed. Do not rewrite historical Requirement, Task,
preflight receipts, attempts, source, Product/Plan or verdicts. A fresh public engineering
investigation after reviewed deployment can append current truthful prerequisites. Original K1
still needs real candidate, independent QA/Review, actual browser and actual live A-to-B evidence.
A successful diagnostic is not delivery DONE. Rollback source and finite enum readers together
before new records; after publishing new detail receipts, retain compatible readers and fix
forward without deleting history. The additive verification-environment spec delta is supplied
separately so root's existing audit edits are preserved.


## Independent implementation review fixes and actual revalidation — 2026-10-24

Independent review identified two defects before integration: the Stage1 guard accidentally
blocked supported non-Python ordinary Responses routes (and unrelated native-host failure could
block ordinary pytest), and mixed Python overflow discarded previously known browser/live facts.
No deployment, production write or K1 execution occurred with this draft.

- RED: new true production-preflight/pre-model regressions and mixed overflow produced10 failures
  and1 pass in2.21s outside the sandbox. A prior sandbox attempt was blocked by trusted process
  observation; initial Responses fixture config errors were corrected before this red run.
- Fix: shared ordinary selector retains existing precise Go/npm/Maven/unittest/legacy pytest
  semantics and ignores irrelevant registered-host prerequisites only for a complete ordinary
  original role group. Explicit capabilities, unmarked e2e/acceptance, unknown entries, foreign
  role/criterion scope and denied current commands cannot fall back. Cache checks still apply.
- Mixed overflow now retains every original prerequisite, with exact unsupported facts for all
  affected Python rows; homogeneous v1's original64-selector rejection remains. Public inspect/
  handle tests retain70 original mappings and exact browser/live remedies without retry authority.
- First focused result:11 passed. A further foreign-scope regression initially failed once,
  prompting shared whole-scope validation for ordinary and registered modes. Expanded suite then
  passed270 cases in112.01s.
- Additional mixed ordinary+registered same-role regression caught erroneous READY. One local
  formatted-text replacement did not apply; the unchanged red case was caught by the next run
  (270 passed/1 failed in110.65s). The exact source edit was then verified, and all6 focused
  ordinary/mixed-role cases passed in1.32s. The test and expectations were retained.
- **Final complete affected+adjacent suite:271 passed in105.14s.** Actual command:

```text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q tests/manager/test_native_verification_partition.py \
  tests/manager/test_native_verification_summary_trust.py \
  tests/manager/test_delivery_preflight.py tests/manager/test_native_verification.py \
  tests/manager/test_verifier_preparation.py tests/manager/test_delivery_wait.py \
  tests/planning/test_verification_feasibility.py tests/manager/test_verifier_capacity_input.py \
  tests/agents/test_verification_output_binding.py \
  tests/recovery/test_verification_output_composition.py --tb=short
```

Final Ruff check/format check and strict Mypy passed on the exact12 changed Python modules
(six production, six test paths). No actual candidate/model/production SQL was invoked. Tests
use isolated Git/SQLite fixtures and fake controlled resource ports; the final command used
normal tool approval for actual local trusted process observation. Actual browser/live business
acceptance remains outstanding and is not established by these regression results.

Independent implementation re-review: pending at packaging preparation. This draft remains
unpublished; root owns integration, the controlled Host boundary and public K1 continuation.


## Final integrated verification and independent review (2026-10-24)

Root integrated the exact independently accepted Stage1 patch314601299e4aa5fc077cfdf8f9d16a74171273fc3531c48eee7dbe19ac6f2400
and legacy bridge code, preserving both production_backend hunks and all prior audit text.
The original bridge manifest's spec body was superseded only by independently read documentation
SHA90c6c4325113d497731dfe74d6b466b951808ba3b4016ee109c64814bc73adbe;
no stale whole-bundle byte-match is claimed. The exact schema-inventory guard repair has its own
red/green and unchanged177-schema evidence in schema-inventory.md. Independent Standards/Spec
reviews accepted both implementations; a final separate review accepted the combined factory
SHAca28471be46f7fe41ec5c4b887d17c697f78b96f6b6dc7347743cacc01dd21ca and inventory guards.

Actual final integrated checks, under normal approved sandbox-external execution:

- Ruff check, format check and strict Mypy on all22 changed Python files: PASS.
- git diff --check: PASS.
- Final21-module suite: **516 passed,11 skipped in286.96s**, no failure/setup error.
  The11 skips are existing v1 capture-reconciliation cases that require the separately
  tested v2 mutation capability (4+6+1 cases); no OS/DB rejection was counted as a skip.
- The suite includes lossless partition/summary trust/preflight/native/verifier preparation,
  public waiting, planning feasibility/capacity, output composition; exact boot bridge,
  knowledge isolation/claim/capacity/replay facts, capture reconciliation and the real public
  stopped-failure PAUSE/RESUME fixture; exact schema inventory and three real Darwin
  owned-session/finalization modules. MySQL safety hooks checked the isolated test DB;
  no production DB/model was used.

Original K1 read-only diagnostic independently reopened its exact approved recovery chain,
anchor plan3cf975409719c9614e4bae771cd72da4db17e8ba5a7d3155bc0c1e4bd6e0a95a,
bindingbff4531e8fcec28f28443a7677a876aa597feaff192c86400b1dbe3493547b3f,
four native knowledge receipts and current main capture-stop. All five current OS rechecks
passed. Diagnostic JSON SHAc258362af5e56f22b4443d15d0bd42b08431fbc4db8e4843b201e712300fe3a6
is evidence of a read-only check, not an authorization, historical rewrite or released retry.
The initial automatic review misread capture_start/capture_stop getter names as writes;
source evidence showed their read-only implementation and normal re-review approved the
same script. The check actually executed; there is no unresolved permission block for it.

Stock-data treatment remains public fresh exact proposal, delegated ENGINEERING PAUSE,
one ordinary work reservation (execution3→4, work2→3), then separate current-fact RESUME.
Keep source5547815464a04991f50a2e0532d6f2f13d8daa69, all29 drafts and every old failure,
proof, approval and Task. No direct SQL writes, source rebase, provider-restoration claim,
candidate or future independent QA/Review verdict is inferred from these maintenance checks.
Stage1 still adds no production browser/live executor; actual browser and live A→B acceptance
remain required after a real candidate. No automation or recurring task was created.
