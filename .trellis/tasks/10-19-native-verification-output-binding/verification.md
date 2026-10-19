# Verification, current data and deployment

## Verified source boundary
The real native-adapter regression failed before the fix: the model's self-authored command
reference was accepted as SUCCEEDED despite the independently executed receipt having a different
URI. Controlled executor count was one. After the fix the same symptom is rejected. The source
worker's focused run passed163 tests in46.21s; two existing explicit local sandbox/toolchain
opt-ins were skipped, so this run does not certify those optional live environments.

Independent production-composition checks passed8 tests in2.71s outside the sandbox, using only
temporary Git/SQLite and fake ports. A test guard forbids constructing a production SQL repository.
Existing Reviewer-only proposal/resume regressions passed10 tests in4.22s. Ruff/format, strict
Mypy of all8 affected source files and the independent composition file, and diff-check passed.
These counts overlap in purpose and are not a claim of total independent coverage.

Historical initial source/spec report:
`/tmp/ase-native-verification-output-independent-review-20261019.json`, SHA-256
`dbe5ecfedf2719b2e37fa197553142d874025859f41fdb196876cf8ba144df0f`.
It bound the8 source files, own composition test and4 documents. Subsequent review identified a
missing symmetric guard: real required command failure must also reject Review APPROVE, not
only QA PASS. Preserve the original report as history rather than presenting it as final approval.

The real native-adapter Review regression reproduced that omission before the correction:
1 failed in1.21s at SUCCEEDED-versus-FAILED, actual returncode1 and exactly one executor call.
The symmetric correction now rejects contradictory Review APPROVE through the existing
VERIFICATION_COMMAND_FAILED rule while retaining honest Review REJECT for returncodes0 and1.
Final native gate plus production composition tests passed31 cases in22.07s; delta Ruff/format,
guard strict Mypy and diff-check passed. The163-case suite above predates this narrow delta and
was not rerun unnecessarily.

Final independent source/spec review passed and binds all8 final source files,4 changed tests,
the existing Reviewer-only test and5 documents:
`/tmp/ase-native-verification-output-final-review-20261019.json`, SHA-256
`4e517d18826d23e248bdce5d98420c7ab1665711b55af2189f2d8786a74b81c6`.
The final review inspected the delta and worker's31-case record; the reviewer independently ran
the8 composition and10 Reviewer-only tests earlier. It did not rerun the final tests or perform
production control. These are maintenance reviews, not K1 QA or Reviewer verdicts.

## Stored data disposition
No SQL or Schema migration and no old Artifact/verdict/reference rewrite. Existing accepted K1
progress still proves lawful preserved draft and continuation, not independently recorded command
execution. Its four historical command declarations stay unverified. New QA/Reviewer must execute
their precise approved final-candidate checks and cite their new real receipts. Missing original
stdout cannot be recreated from declared SHA, and no data repair can manufacture it.

## Live K1 observation during this work
Task `task_recovery_711a755e5852a52346876a7b07376311` remained active throughout implementation.
Run3 reached its local limit with no final output; the actual09:03:58.385721Z native stop has an
owned-session-empty proof. Outcome remains FAILED/WORK_INTERRUPTED, SHA-256
`060cc489451989a6f5892df91f6dd8f7d36e82dac28dddae3dc1ee842addd7fd`.
Its exact full mutation receipt, admission and retained workspace authorized a fresh Run4, not
a replay of Run3 or an accepted completion for step3. Run3 lease released09:04:24.074437Z.

Run4 `run_5afbe01dc44245f8a06f1cc3daa7a2db` started09:05:51.118902Z, new Context
`ctx_ca07ef33e569a58878ab5f06f788ce7705c2d4d3db5fa9333347a90e8080fa18`, active lease
`lease_b56a5687b4366ce0e1bf65c8`. The exact immutable receipt/admission/start chain and rendered
Context independently retain all225678 bytes of the complete inherited patch. No extra Continue,
Plan approval, service stop or direct SQL modification was needed.

Root's bounded file-only audit `/tmp/ase-k1-run3-run4-continuation-audit-20261019.json`, SHA-256
`bbcf039f12349c8513c14f614172dc8b88d4ebdf127367d3b8b432193da1a67f`, binds receipt
`f5206147900e4b32be37d4f531ec3c270f2135468a1dfd207ec661746dd51d5d` and admission
`a11f705711c618aebad27b2c2f9dc563edfa928badc82bfb20f39a2fb91d0d5d`.
It did not revalidate the subsequently live workspace, acquire a fresh SQL claim authority or
capture provider stdin. SELECT-only stage snapshot16 separately observed new Task attempt4,
revision8 and its active lease at09:06:34Z. No candidate or independent QA/Review existed then.

Later SELECT-only snapshot18 at09:17:59Z observed the same IMPLEMENTING/attempt4/revision8,
active Run4 heartbeat09:17:53Z and no new candidate/publication. Its SHA-256 is
`542de6a129ca47e47842f27368ba8fb5008a5a3bd1f2ea73a076485b729ef35f` at
`/tmp/ase-k1-stage-snapshot-20261019-18.json`. No duplicate Continue or service signal was sent.

## Deployment and rollback
Reviewed repair `e309f0ba7418569010b942cc4374f7fe243090a5` was committed, independently
bound and pushed. A bounded foreground exact-Run4 observer saw its natural completed stop at
09:32:37.636722Z, output present and owned-session-empty proof; no original role was signaled
to force this boundary. The subsequent official stop established READY and actual service exit.
Its trigger observation is `/tmp/ase-k1-run4-stop-maintenance-trigger-20261019.json`, SHA-256
`e60b036eb13ce7b36f90f42f406dd3fc8c4a6b479d7113b30406be58931ba092`.
This was a foreground single-event observer, not a scheduled task or recurring automation.

SELECT-only snapshot19 at09:33:55Z, SHA-256
`3ee433346477788329c21119353862cd97fd496322fa5f93f5b20588e7934322`, confirms Run4
SUCCEEDED and formal progress `art_coder_2dd86c54a6f2a7a6ef5ba7b020b9c6f8`, artifact SHA-256
`3d342b359fd2d5d924d84c13657cd7996e394ac4ee8a215b4696b2bc840ed7f6`, accepted in
CONTINUE_REQUIRED/QUEUED before attempt5 reservation. The progress cumulatively completes
steps1–3 of8; there is no candidate or independent QA/Review. Run4 lease is RELEASED.
Next WorkItem `work_210001bf077c1479ae8b9381fe384beda4762e392a960f4db0d6760cd3a93ddd`
was claimed and released into WAITING_DEPENDENCY; it has no main-role InvocationStart. Its
knowledge preparation did record FAILED/SERVICE_PAUSED with no execution observations, so that
empty list must not be relabeled as trustworthy historical no-start evidence.

After official stop, main was fast-forwarded and pushed to e309f0b; the new service started as
PID18292. Public Console readiness is true, mode normal and operation contract version10.
The K1 Task's approved source stays fa3589a. A read-only target-clone HEAD observation instead
showed08f45c1 (prior audit-only documentation); no target checkout/rebase was performed.
Public Continue `operation_a35a30f58f12a088d935fe2129474212` completed its evaluation but left
the original Requirement in DELIVERING, current parent checkpoint
`77eaff6f2a6004df8e71d2c94f3973785406c2b611e951d513d0e1c84bf4fbdf`.
The missing trustworthy knowledge admission-pause receipt/recovery seam is separately tracked in
`../10-19-paused-knowledge-recovery/prd.md`; no SQL repair, old-fact rewrite or new Requirement.

Independent static preparation confirms the native Supervisor is the preferred candidate
QA/Review path. The approved Plan's33 unique pytest nodes fit the current shared64-node bound;
the obsolete32-node phrase in verification-environment documentation was corrected. Mixed
Node/browser and live A-to-B requirements may need actual capabilities not supplied by isolated
Python/MySQL. This is conditional static analysis, not an observed candidate verification wait
or approval for future execution. Do not relabel fixtures as browser/live acceptance or force a
nonterminal Task into standalone terminal verification. Use actual candidate preparation facts.

Rollback uses the same controlled idle boundary and retains all old/new execution records,
approvals, claims and drafts. Reverting the guard cannot grant an admitted verification replay.
The original native Coder per-command capture limitation remains; this bounded repair secures
the existing independent verification receipts rather than claiming a new trusted command channel.
