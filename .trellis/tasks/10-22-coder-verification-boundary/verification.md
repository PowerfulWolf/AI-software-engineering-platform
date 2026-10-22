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
