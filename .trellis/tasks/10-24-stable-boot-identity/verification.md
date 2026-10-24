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

## Actual release and original K1 public recovery (2026-10-24)

Released maintenance commit `ff1d9c6339f980f5a2fe2c352b3554601d721dc4` by verified
fast-forward to local/main and origin/main. Main checkout and maintenance worktree
were clean. The official controlled service lifecycle drained Host PID34401,
verified durable completion and its actual exit, then started Host PID52238 from
released main. A sandbox-external status check confirmed the managed identity and
normal operation admission. No force termination, lifecycle deletion or automation.
The K1 target clone remains `5547815464a04991f50a2e0532d6f2f13d8daa69`.

Fresh public preparation `operation_aca86164f0ced973d23f77a7d70ea2a0` SUCCEEDED with
plan `3eeafbe15b9505437ca4e040c1148d4ebe3bfd415df9cda2c4c794843da584b9`.
Independent read-only review validated typed operation/plan integrity, exact original
failed invocation and approved lineage, all29 complete draft bodies/patches/original
Git blobs, unchanged HEAD/index/branch, frozen permissions and complete2990-file
inventory `85859671974fa3ffc9c7c8139c9154b58ef2818771a51801dded6ef265b9a54d`.
The delegated engineering reference explicitly accepts unknown EOF cause and one
ordinary-work debit (work2→3, execution3→4; frozen maxima10/40). It neither asserts
provider restoration nor grants Schema/Trellis/AGENTS authority or future verdicts.
Reviewed intent SHA `bed41d664132af9ad4eae940bf2202701267dd5eea263cfa97bd268e054dda01`.

Public PAUSE `operation_2813aad3db58caf95fa341b66168eaaa` SUCCEEDED in111.943369s
(request13:06:13.561110Z, updated13:08:05.504479Z). New binding
`0a2fc13f342cf652fdc430e872aca8b99d7202ab176cbe21ce77603d6f6952ce`, sequence2,
retains exact source/base, worktree/branch and identical before/after inventory.
Latest public snapshot confirms old failed work closed, new exec4 WorkItem
`work_0a2fc13f342cf652fdc430e872aca8b99d7202ab176cbe21ce77603d6f6952ce`
WAITING_HUMAN without Agent/lease. Task stays IMPLEMENTING at revision2;
Requirement checkpoint `bc9443b92968a6fbcf085bb574e9d24bf7a11bb3ad059a141bb8f94029c25f64`.
Its exact paused disposition is
`24e4c472050faad22b742fab19c50f6e7565524797120b7f42a04b53a958f8c6`.
Actual browser read showed the same original K1 and retained-progress pause.

存量数据处置：全部通过公开 typed Operation，不直接写 SQL、不重建 Requirement/Task、
不重算历史预算，不删除旧失败/UNKNOWN、claim、proof、approval或草稿。上述 PAUSE
不是候选或交付完成；须另行最新精确 RESUME，再新 claim/Run/Context 及独立 QA/Review。
当前29份草稿仅覆盖基础采集账本/来源/位置/staging，生产接入、Console及实际 browser/live A→B
仍未完成；两个计划验收文件尚不存在。保留全部验收要求，不以 Python 子集替代。

Separate RESUME `operation_4ed19fa448e2edc24e96fe059192c0b7` was submitted through
public typed API at13:14:36.360477Z after independent review of intent
SHA `8b61f555fec223b2953f170fcec0c031924bc03bfd27c7195e01388a498ecda8`.
The reviewer reopened actual persisted binding, latest disposition, complete current
inventory and release code: one existing WorkItem is released; there is no second
ordinary reservation. At13:18:17Z public summary showed the same exec4 WorkItem
RUNNING with a fresh valid lease and heartbeat. Original Task revision2 and source
remain unchanged; this is execution admission, not accepted code or a verdict.

Actual knowledge intent began13:17:32.800839Z, independently decoded from the private
read-only KnowledgeRecordStore with envelope and typed digest validation:
Run `run_knowledge_f4c7c80c8433b3dffd17bb7ba30511e4`,
Context `ctx_34b9a9bdc78011b6d4fe5a858264e967cd28679714f097672d53a77a53928412`,
lease `lease_e2b810428daf6e84686d1fed`, intent
`02ce5695f91e77cc1d92abdec37179e49ab3c31db7ab03c2a3187099ad8b727d`.
At13:22:20Z heartbeat was valid and Coder remained in knowledge preparation;
no current main invocation start existed at the preceding read. Actual browser
showed original K1 in progress (1 active,0 blocked). The temporary browser tab
was then closed. No assertion of model completion, candidate, QA/Review or
Requirement DONE is made; continue active supervision through those real facts.
