# Verification and original K1 treatment

## Code and contracts

Shared Coder system guidance now distinguishes explicit Coder obligations and genuine
implementation dependencies from independent QA/Reviewer execution prerequisites. Both
request and persisted Context prompt builders use it; native compilation inherits it.
Final-slice prose specifies required Coder verification. Native tooling no longer implies
that every unavailable independent verifier blocks other permitted implementation.

No Task/Plan/Context/artifact/output schema, permissions, candidate acceptance, retry,
queue or QA/Review gate changed. No production SQL was written. This fixes ambiguous
platform prose; it does not prove that a model will complete the remaining K1 work.

## Executed checks

Interpreter: main checkout `.venv/bin/python`, PYTHONPATH=src in maintenance worktree.

```sh
python -m pytest -q -p no:cacheprovider --tb=short \
  tests/agents/test_coder_slice_output_guidance.py \
  tests/agents/test_negative_credential_prompt_guidance.py \
  tests/agents/test_codex_cli.py tests/planning/test_execution_window.py
```

- Before implementation: six new request/context/native guidance cases failed; seven
  negative/compatibility/native-NOT_RUN cases passed. This establishes the missing prose
  and existing honest-NOT_RUN candidate behavior, not a causal proof of every old delay.
- New focused file after implementation:33 passed.
- Full command inside outer sandbox:104 passed;10 real owned-process observations failed
  because OS observation was denied. No test was skipped or changed to bypass this.
- Same full command through the authorized sandbox-external execution: **114 passed**.
- Scoped Ruff, format, strict Mypy and git diff check passed.
- Independent review covers the unchanged machine gates and retained Coder obligations.

## 存量数据处置

Original K1 attempt7 produced coder-progress `art_coder_9cfe2ac47d2452336216cec6f045ade4`;
26 retained changed files, only steps01/02 completed,03–08 remaining. It is not a candidate.
At `2026-10-22T08:03Z` public observation, attempt8 was waiting on real knowledge gap
`8e7a2b186c78c96d41972b6e57927bbfd4111da4cf919437d405fbd03feaa14e`;
both knowledge subcalls returned, no main invocation had started. Parent checkpoint
`7f7b1b187dd7a679ab8f3b80683f0b054c7626052fb9f5a331dc375b86b79a30`.

The gap asks whether isolated SQL, real browser and actual ASE A-to-B verification are
all ready. They have not all been demonstrated. A separately reviewed factual resolution
must say so, clarify the original role boundary and preserve actual implementation
dependencies. Use the existing exact knowledge-resolution approval and public Continue;
do not fabricate a gap, inject a prompt or reset the Task. The frozen source remains
`5547815464a04991f50a2e0532d6f2f13d8daa69`; old records stay unchanged.

Deploy only after the service's controlled drain and real exit, then reconstruct the
Host. Future prompts consume the fix. Preserve the current original knowledge wait,
progress, approvals, counters and failure history. Browser fixture execution and live
A-to-B are still separate missing prerequisites, never replaced by this maintenance test.

## Rollback

Revert the maintenance commit only at a verified controlled stop and reconstruct Host.
No record reader/version migration is required. Preserve K1 and its worktree; do not
delete a resolution, pretend NOT_RUN was PASS or roll back source/budget/history.

## Actual deployment and continuation

Runtime commit `79972a89600de45d75e0677c63ecd512fc700afe` was independently reviewed,
fast-forwarded to main and pushed. The official service stop recorded READY for original
PID45506/instance `console_instance_0e384478072e65dd81ebb06bde8b7be6` at
`2026-10-22T08:23:44.675920Z`; the wrapper confirmed the process stopped. New PID21024,
instance `console_instance_d7fcfb644909cff745d13bb8b060ab55`, started at
`2026-10-22T08:26:27.320984Z`. It is an updated platform Host, not a new K1 source baseline.

The independent factual-answer review accepted payload SHA
`80ed42403c95473a86de6146e49aeea106aaf7b1a6b6d0fb36662899798f170d`.
The public knowledge-resolution endpoint sealed original gap8 resolution
`ca22eb183b5dfd9677ba86c6b9293ebddb40af066c3d8f3b594265657e807fc9`,
approved_by=human:local-console under the user's existing delegation, REQUIREMENT_ONLY.
It explicitly says browser/live readiness is unproved and retains all original SQL,
implementation dependency, slice, candidate and independent verdict obligations.
The specialized recovery-fixture database name is not generalized to other K1 tests.

Public Continue Operation `operation_8ba869012ecce560f320acfcace9df88` was submitted once
with its fixed idempotency key and exact parent checkpoint; it was subsequently RUNNING.
The existing attempt8 WorkItem resumed with new real lease
`lease_3528cf5dca037882fbfc8691`, without a new ordinary attempt reservation or refund.
The SELECT-only snapshot at `2026-10-22T08:37:34Z` showed IMPLEMENTING/revision14,
attempts8, ordinary work_attempt7/max10, source unchanged and an ACTIVE new claim.

New knowledge intent/assessment both returned. Main Coder started at
`2026-10-22T08:41:45.847890Z`, Run `run_58dae5d3e8b4458dbc7c5cbdd952a434`, exact Context
`ctx_d31fdc3090c0d7dd3adc8c4eeda40937b1cc2b8bf9b9ca3207b3719a5dbba768`.
Start SHA `8999346dcf6ee3853b30d76635c27e76348c0effb67d0d4113c020f3f6b9e644`.
Typed read-only Context validation confirmed the new resolution is actually included.
The original slice selects steps03/04, inherits01/02 and defers05–08; it was not widened.
At the `08:42:53Z` observation, no main outcome was sealed. This proves real continuation,
not subsequent completion, a candidate, QA PASS, Review APPROVE or K1 DONE.

Automatic approval occasionally failed because its reviewer model was at capacity or
timed out; unexecuted actions were retried through the same normal review channel.
No approval check was bypassed and no unresolved permission rejection remains for the
completed deployment/approval/Continue actions. No automation or recurring task was created.

## Attempt8 stopped failure and exact terminal recovery

The main call ended at2026-10-22T09:03:23.134529Z. Original outcome
`77be17ac980cc979fae8782f03bf8f94e36fe39b1ae4beaf407b8a84e2729be1`
is FAILED/POLICY_VIOLATION with no artifact. Its fixed metadata says rc1 and
UNKNOWN_EXIT_TRUNCATED. Capture stop
`94973e081e9baff9d2d1ffa1b3d02f63fc25ab4177144b3257f5bf6debd60a4e`
separately preserves failed/rc1, original PROVIDER_UNAVAILABLE, cause=None,
output absent and an owned-session proof. The native adapter wraps changed
workspace after a failed call as policy failure; this alone is not a finding
of an unauthorized path. The underlying CLI failure remains unknown. No old
error, outcome, transient flag, artifact, stop, budget or verdict is rewritten.

Independent complete observation found14 noncache changes since this call
started:11 modified regular files and3 additions, no deletes or mode changes.
All14 paths passed original frozen read/write policy. This is path evidence,
not full recovery authorization. The same-Task stopped_failure v1 correctly
refuses new source mutations and was not widened. The existing terminal
recovery path is applicable because the actual native Task/cursor is BLOCKED
and has no candidate. The execution result FAILED is a different fact.

Public proposal Operation `operation_e8b42c89cef7d549b86dc2af43e07b6f`
succeeded and produced exact plan
`3a4325237347c8caf434d94379cce745a9fe9d4f4f5298c99a9c0b59a10e7e18`.
An independent typed-store review checked29 captured files, complete244526-byte
current patch,2994-entry snapshot
`24a0b41ce52f2003721fbc343ff7f3b2f734599bf3fc3fc6d1e09067bd83b943`,
and the full225678-byte inherited patch. Source, capture and target all remain
5547815464a04991f50a2e0532d6f2f13d8daa69. Target clone and running platform
checkout are different roots;79972a8 is the platform runtime, not a new K1
execution base. Permissions and policies are unchanged; schemas/Trellis/AGENTS
writes remain denied. input_mode=None strictly seeds the current draft; it
does not grant a new coder_reapply conflict-resolution mode.

After review, the existing delegated engineering approval was submitted only
through public Continue, binding exact plan and parent checkpoint. New Operation
`operation_df3a5439aa1f7b8719a65383dbdd51d1` was QUEUED and then RUNNING at
2026-10-22T09:36Z. This submission is not proof of completed recovery, a SQL Task,
a new Coder invocation or delivery. The service must freshly recheck stop, full
workspace, claims and current facts. Old Task/history remain; approved terminal
recovery creates `task_recovery_3a4325237347c8caf434d94379cce745` under the original
Requirement with the exact target authority. No direct SQL or store writes,
manual dispatch, replacement Requirement or baseline update is used.


## Recovery6 actual seed, claim and main invocation

Read-only typed preparation records for the same single public Operation confirm
AUTHORIZATION_RECORDED at2026-10-22T09:38:41.997954Z, TASK_SEALED at09:40:53.793343Z,
DISPATCH_COMMITTED at09:52:24.784657Z, SEED_VERIFIED at09:54:26.840635Z and
EXECUTION_CLAIMED at09:54:34.668289Z. Exact dispatch SHA
`f4bd80711c538ed541ac9baec5f3f25a0076989f1f6a0820a474b33c8de8de9c`,
seed record SHA `78d04238ebaf80fd26cc4bf60d6dc6e155fb66d71391c5af0a5d628a0638a6b9`,
input_mode=preserve_draft. The preparation duration is observed, while its
function-level cost attribution has not been measured. Static nested-call counts
alone do not prove the active bottleneck or process liveness.

New WorkItem `work_e67c8e9f89e629d1d99c66e81d39cba7ea8701f5ab5d459cb37da451bf94a35a`,
lease `lease_bc066354bb550bbc4058d231`, assignment
`assignment_6ad2f37f6a2dd54121e28fcc`, claim SHA
`6e36b0290140885750f96cefca39f0c73c1899579cf9f8f143e5da8b1fde38ec`.
The main invocation journal independently confirms Run
`run_54e478c8599c422abc109e4333997be1`, attempt1, source5547815 and Context
`ctx_4961bab17f5f7221c17fa5d0a6155f2e4ae6410fd1334a123b8d9b6936d9a883`.
Start at2026-10-22T09:57:37.950526Z, SHA
`0258bfec08f33ac9ee57f87216334e73683372d325195ae56fbe542679ef1db5`.
Its knowledge intent genuinely returned at09:57:05.530361Z. At10:03:22Z no
main outcome was present. These are execution facts, not implementation completion,
a candidate or independent QA/Review verdicts. No duplicate Continue was submitted.

The normal automatic approval reviewer remains intermittently unavailable with
Selected model is at capacity: some read-only SQL/GET operations succeeded,
while later read-only SQL, process-status and maintenance-worktree writes were
NOT_RUN. User guidance was requested asynchronously; unaffected temporary-directory
implementation, bounded tests and typed file reads continued without bypassing
approval. This tool-service failure does not change existing engineering authority.


## Recovery6 stopped failure and same-Task approved pause

The prior 10:03Z no-outcome observation is superseded by the sealed later facts:
Run run_54e478c8599c422abc109e4333997be1 failed at2026-10-22T10:04:56Z.
Outcome SHA5980f4aba80d3dbf2e2ce8b2419b31f966c75f526620b9e7df4e18286506c722
is FAILED / PROVIDER_UNAVAILABLE / transient=false, no artifact, rc1. Its safe main
error says stream disconnected before completion: stream closed before response.completed.
The underlying cause is unresolved; no quota, authentication or transient cause is inferred.
Stop SHA c2240b79f87dce57fedfa05206f4f64f666795ea2023d2f3eca6e88aa3bbfd2e
records failed/rc1, no output and a real owned-session-empty proof. The claim was
RELEASED at10:04:57.273173Z. Old outcome, stop, budgets and Task histories remain immutable.

Public inspection operation_a8e04a3d27237d9c5c284c8ddbb3da25 found no acceptable output.
Public preparation operation_843a7f9244d63f2b437becb72867bea7 produced same-Task plan
916ad4557b6060390777fc33eb6921973bf51b5ef5d6de8807e6e54eb6f0f949.
Independent typed and complete-workspace review checked2990 inventory entries,
SHA85859671974fa3ffc9c7c8139c9154b58ef2818771a51801dded6ef265b9a54d,
and29 legal retained draft files; start/current noncache mutation delta is zero.
Complete current244526-byte patch and inherited225678-byte patch remain retained.
Task/source/worktree are unchanged; target baseline stays5547815464a04991f50a2e0532d6f2f13d8daa69.

Delegated engineering approval used public Execute(PAUSE) exactly once:
operation_00e4383c4a821b529212d1f87ef743f8 is SUCCEEDED / ENGINEERING_BASELINE_UPDATED.
Binding45a0a025111e8d31f99a24a3b7b3a6235244e08351b6d955051738933d3c82eb
holds new coder WorkItem work_45a0a025111e8d31f99a24a3b7b3a6235244e08351b6d955051738933d3c82eb
in WAITING_HUMAN, attempt2, and closes the prior attempt1 item. A fresh public snapshot
confirmed Task IMPLEMENTING/revision2 and EXECUTION_BASELINE_PAUSED, disposition
532cc5173cfcea081f8753788e35d53d6454e0b3b57e578ded6d2a012a17346d.
Exactly one ordinary generation1-to-2 was reserved, with no refund. Separate fresh exact
RESUME is still required; no candidate, QA PASS, Review approval or DONE exists yet.

The reviewed forward-only native JSON diagnosis fix is applied to the maintenance worktree.
All13 files match frozen-v2 hashes; applied Ruff check/format pass. The patch never
rewrites historical causes or grants recovery authority. The automatic permission reviewer
still intermittently returns capacity errors: the first fresh GET was NOT_RUN; a normal
retry succeeded. No permission review was bypassed and no recurring automation was created.


## Diagnostics release and actual original-K1 continuation

Reviewed maintenance commit1ec4edd6f08bb09e8709f2c3e7519d734ee98f46 was fast-forwarded
to main and pushed to origin/main. Applied Ruff check/format passed; applied strict Mypy
passed for all8 changed Python files. Prior red/green real-child and independent review
results remain recorded in the native-json-failure-diagnostics task. No new dependency,
Schema or database migration was introduced.

The old Host completed public controlled SHUTDOWN: current operations/writes saved,
executors/index stopped, lifecycle READY confirmed, and the old process exited normally.
The service script started the replacement Host PID44153 from the released main checkout.
No force kill, lifecycle deletion, secret output or automatic recurring task was used.
K1 stayed at its exact approved pause through maintenance. Registered target clone HEAD
was separately rechecked as5547815464a04991f50a2e0532d6f2f13d8daa69 before RESUME.

Fresh post-restart public summary and full Task detail matched binding45a0a025...,
new waiting work item and disposition532cc517... . The independently checked temporary
typed client submitted ResumeExecutionBaselineIntent once through POST/api/v1/operations,
fixed key k1-recovery6-stopped-failure-resume-20261022. Resulting Operation is
operation_ce817eb979874d7d6f29a533dfeac64f; it was RUNNING during the live role.
This control action is distinct from the earlier PAUSE and is not delivery completion.

Attempt2 knowledge intent genuinely returned. Its assessment failed at10:41:38.053262Z,
outcome ef3525ab3d35b9e91cdfc3f609abf77e0c4ac69dec74eaaf44595cc4d5cf5ee9,
PROVIDER_UNAVAILABLE/transient=true, with actual native-stop and HTTP observation records.
The local-proxy diagnostic body was deliberately hidden; no underlying cause is invented.
Its lease was RELEASED at10:41:39.588167Z. Normal frozen transient policy closed that
queue generation and created execution attempt3 with a new claim; root did not submit a
second Continue/RESUME or change policy. SELECT-only consistent snapshot at10:51:32Z
confirmed Task IMPLEMENTING/revision2, execution attempts3, ordinary work_attempt2/max10,
max_attempts40, source unchanged and an ACTIVE new claim. Thus transient execution identity
is not an extra ordinary work reservation or refund of the original stopped failure.

Attempt3 knowledge intent and assessment both returned through actual model calls.
The new main Coder started at2026-10-22T10:50:03.619668Z, Run
run_cac817b0ee234eb790c3eadb73705b52, Context
ctx_dea4a0d9b4012175102d6be3816ae62451c4fe4c141ea8217facf96d7f9ab707,
lease_9b7eda6efab256b04a0616d2, WorkItem
work_99a5e2ecaf8c87506feb702eb8b90a35b0d8072e17f970a325d7a6cdcde425d7.
Start SHAba0cb8d44cf166bcc9dec03d0f6d3a73077c09a910107e058814fc45561ecb8a
binds the unchanged Task/source. At10:50:15Z no main outcome was sealed. The original
Requirement is now genuinely executing, while candidate, independent same-candidate QA,
Review and Handoff remain required. No DONE or future verdict is asserted.

Later at10:54:32Z the same new main Run had a sealed FAILED outcome,
SHAa351f0d45e35a1adc9c6eea3890eef86debdf950b06405eac2fd4cb0f5aca8b5,
PROVIDER_UNAVAILABLE/transient=false, rc1, no artifact. The new safe native message
preserves: stream disconnected before completion: stream closed before response.completed.
Thus diagnosis visibility is deployed, while the underlying stream problem is unresolved.
The RESUME Operation subsequently SUCCEEDED at stage DELIVERING with new parent checkpoint
bc9443b92968a6fbcf085bb574e9d24bf7a11bb3ad059a141bb8f94029c25f64;
this reports the control action, not a successful Coder result or completed delivery.
Root is investigating local-proxy/upstream SSE and exact route facts before approving
another ordinary attempt; no blind additional reservation or failure rewrite is performed.

Stock-data handling: all old Task/outcome/claim/approval/stop/patch bytes remain; exact
public PAUSE/RESUME and ordinary work accounting restored the same Task/source/draft.
No production SQL writes or baseline rebase/replacement Requirement were used. On a future
failure, preserve its own facts and use the applicable fresh public recovery gate. Runtime
rollback must start with a controlled stop and retain all published diagnostics/readers.


## Retained attempt3 facts and verification feasibility follow-through

A fresh public InspectDeliveryWait operation operation_d7f60a8977c1069e83cca08f593e9290
SUCCEEDED at ENGINEERING_INVESTIGATION, without retry/resolution. The old generic
CHECKPOINT_UNAVAILABLE/OUTCOME_REJECTED report was preserved; it is not an execution permit.
SELECT-only consistent snapshot at2026-10-22T11:03:42Z showed Task IMPLEMENTING/revision2,
execution attempts3, ordinary work2/max10, source5547815464a04991f50a2e0532d6f2f13d8daa69;
all three original claims were RELEASED. No SQL write or counter refund occurred.

Independent read-only original capture/outcome checks at11:19:33Z validated stopped failure
proof a9d4024d8bee3903a745211f613f98f29535c8de38acc4f9410a604758a98975,
stop observation0950ad5cec58b1d1e0501dee096ce4cef02cc1941de35c598448c02cec4c348d,
actual failed rc1 and owned_session_empty. Complete current inventory has2990 entries and
SHA85859671974fa3ffc9c7c8139c9154b58ef2818771a51801dded6ef265b9a54d,
identical to the original capture-start inventory. All5 modified and24 new source drafts
remain; no file changed during that invocation. This temporary read-only report is a diagnostic,
not a replacement public recovery authorization or a production artifact.

The actual selected Coder route was codex_cli/proxy/gpt-6.1-sol/xhigh, one route attempt,
not a Responses failure followed by fallback. Recovery composition currently selects a single
CLI provider and freezes dispatch policy. Settings reordering cannot amend a retained Run.
No routing, ModelPolicy, old dispatch or failure classification was altered. New recovery
Task admission also requires a genuinely terminal source; do not force a nonterminal Task
into BLOCKED merely to select another provider.

A real CLI0.162.1, binary SHA74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0,
ran three credential-free synthetic loopback SSE cases. Complete and7-byte-chunked completion
succeeded with rc0/one request. EOF before response.completed reproduced the exact production
message, rc1/real failed stop/no watchdog; CLI made6 requests before failure. Results SHA
f49d235a621fddfaf686bffebeaddfdbcd1b8decc726547a5af7028b249298f7.
This proves a protocol-incomplete stream can cause the symptom, not why the production proxy
or upstream ended it. No real provider or K1 Context was used for these three cases.

A separately approved Docker browser synthetic experiment v1 actually rendered, clicked and
captured a960x640 PNG, but a second-page crash prevented its host-file negative. It stays FAILED,
root cause UNKNOWN, result SHA3d522811c78ae55ed6ea9f750b553ebac821f1c2e5850049a07179d9f70b602f.
Independent review accepted v2, planbe80c8ea2316dbb5173132b1351c950ce37fb5ec85974c2b857c36140b995e77,
with the same permissions/resource/profile and an existing-page file negative. V2 actually passed
render/pointer click/PNG, Node EROFS/ENOENT/EPERM negatives, NoNewPrivs1/Seccomp2/CapEff0/AppArmor,
renderer failed fetches and explicit ERR_FILE_NOT_FOUND. Its result SHA is
7bf3688d5194526fcadf40ddbf9d6159507155e845e3e19c6780296801271d35;
output index SHA b1c3faea2525feb3cf821070170369a3f24cc4d103ca6e6e0b34d319ed4f3766.
Owned containers and synthetic host sentinel/socket were removed with exact absence checks;
cleanup_errors was empty. No shared image/cache prune occurred. Docker is the isolation boundary;
Chromium inner sandbox=false was explicit. This is feasibility research, not a production
capability registration, candidate acceptance or K1 QA/Review.

Independent mixed-verification design review rejected promoting an in-process pytest summary to
trusted per-selector coverage. Its real synthetic conftest counterexample ran no tests with rc0
while emitting a forged collected1/passed1 summary. The proposed aggregate was not implemented.
Revised staged design keeps all61 original mappings, original Python receipt execution and exact
missing-capability discovery, with browser/live requirements still outstanding. See the reusable
trust boundary in verification-environment.md. No source/Plan/permission/QA verdict was changed.

Stock-data handling: existing Requirement, original Task/history, current stopped Task, all29 drafts,
full inherited patches, exact approvals and budgets remain intact. Current K1 has no candidate,
QA, Review or Handoff. A future continuation requires fresh public exact preparation and decision;
no partial experiment or diagnostic success waives original real-browser and real A-to-B acceptance.


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
