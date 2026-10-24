# Stable owned-session boot identity: verification

## Reproduced platform failure

Both original K1 baseline PAUSE operations failed with ContinuationRejected before
process birth/SID inspection. Read-only typed original knowledge receipts retained
`darwin:1790382041:923841`; current kern.boottime was
`darwin:1790382041:848621`. A controlled ASE restart did not change the refusal.
The original proofs, failed operations, Task, ordinary budget and 29 drafts remain.

New native stops use canonical hashed kern.bootsessionuuid. The original wire model
and proof hashing are unchanged. Old mismatches remain rejected without separately
validated exact-record continuity. No boottime seconds tolerance or skip flag exists.

## Actual root checks on 2026-10-24

Interpreter: main checkout .venv/bin/python. PYTHONPATH=src in this isolated exact
1ec4edd source mirror; PYTHONDONTWRITEBYTECODE=1.

- Before implementation, six darwin_boot cases failed because the old query read
  kern.boottime; after stable UUID implementation the six passed.
- Before continuity seam/final boot recheck, two focused cases failed (missing
  keyword and a mid-inspection boot change accepted); both passed after repair.
- Complete inspection file excluding two real OS cases: 34 passed.
- Authorized real Darwin subprocess suite: 71 passed in 11.44 seconds:
  `pytest -q tests/execution/test_owned_session_inspection.py tests/execution/test_owned_session_stop.py tests/execution/test_owned_record_finalization.py --tb=short`.
- Scoped Ruff check and format passed; strict Mypy passed for owned_sessions.py
  and test_owned_session_inspection.py.
- Independent check found no stable UUID implementation defect; import order and
  stale kern.boottime spec wording were corrected. Full-size malformed UUID
  negatives exercise ASCII, embedded NUL, trailing bytes and UUID rejection.

Independent schema checks found two failures also reproduced on unchanged 1ec4edd:
the exact NativeProcessStop embedding inventory omits the existing
rejected-knowledge-current-draft schema. Nine other schema cases passed. No claim
is made that this baseline issue passed or was fixed by the UUID change.

## Transport diagnostic: separate evidence

The previously reviewed 480-second tiny CLI/proxy probe actually succeeded once
with synthetic input only in 20.263963 seconds. Independent typed validation
checked exact admission/native-stop binding, stop proof integrity and complete
before/after credential scans. Manifest:
`/tmp/ase-codex-proxy-tiny-validated-manifest-20261024.json`, SHA-256
`3d0ab03ec50727c39420414277e98ddd947bfb6b2584b70014a8fca27af33558`.
This is neither K1 acceptance nor proof that its prior EOF failure was resolved.

An event-only bounded parser read only fixed nonsecret proxy-default scalars:
request-retry=3, max-retry-credentials=0, max-retry-interval=30,
nonstream-keepalive-interval=0, codex.stream-bootstrap-buffering=true,
codex.stream-bootstrap-timeout=0. The two streaming scalars were absent. This
proves bytes in the Homebrew default file, not the live proxy's effective config.
No raw config, raw hash, secret, arbitrary scalar or provider log was exposed.

## 存量数据处置 and rollback

No production SQL or historical artifact edits. Current K1 remains the original
Requirement and Task at source5547815464a04991f50a2e0532d6f2f13d8daa69. An exact
historical approved stable-boot anchor and full recovery lineage must be validated
before original stops can pass with the compatibility bridge. Fresh public
proposal, explicit PAUSE, then separately revalidated RESUME remain mandatory;
no execution has been released by this isolated code/test work.

Deploy only at a verified controlled idle/exit boundary after complete bridge
testing and independent review. Retain readers for newly generated proof strings.
Rollback at the same controlled boundary; never erase proof/history, refund a
failure, reuse a closed claim or accept a draft as a candidate/verdict.

## Explicit legacy bridge checks (child implementation, October 24)

New `test_owned_session_boot_bridge.py` has 41 passing cases in the affected suite:
real private FileExecutionBaselineStore approval/proposal-only/scope cases; real
FileRecoveryStore approved edge and missing/changed ancestry; exact original receipt,
outcome, independent execution record, Context and capture envelopes; conservative numeric
and time rejection; original live leader/birth/SID; default strictness; stable boot/account
change around the double scans. File/chain tests assert complete original JSON bytes remain
unchanged. Synthetic witness tests intentionally isolate store validation from the lower
OS seam; they are not production stop evidence.

Actual command, in this isolated mirror:

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src <trusted-python> -m pytest -q \
 tests/manager/test_owned_session_boot_bridge.py \
 tests/manager/test_knowledge_isolation.py \
 tests/manager/test_baseline_knowledge_claim_proof.py \
 tests/manager/test_capacity_legacy_claim_snapshot.py \
 tests/manager/test_replay_guarded_claim_observation.py \
 tests/orchestration/test_capture_reconciliation.py --tb=short
```

Result in restricted sandbox: **159 passed, 11 pre-existing skips, 1 failed, 1 setup error**
in 110.71 seconds. The failed real native preparation lacks permitted Darwin OS inspection;
the public regression setup is denied the local MySQL socket with EPERM. This is not a full
suite pass. The parent must rerun this exact affected suite serially outside the sandbox,
including its identity-checked isolated database, before deployment. Existing skipped v1
capture cases explicitly require v2 retained-source/mutation capability and remain skipped.

Ruff check and Ruff format check passed on the seven bridge implementation/test paths.
Strict Mypy on the same paths passed before the final extra envelope/temporal tests; the
final same-path rerun is recorded separately after completion. No real model, production
write API, SQL mutation, historical proof rewrite or K1 resume was performed by this child.

Final strict Mypy rerun on all seven bridge implementation/test files passed after the
extra temporal, envelope, ancestry and OS-double-scan tests. Final Ruff check and format
check also passed. Source/test logic is now frozen for independent review and exact parent
integration; the preceding sandbox suite failure/error still requires the outside rerun.


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
