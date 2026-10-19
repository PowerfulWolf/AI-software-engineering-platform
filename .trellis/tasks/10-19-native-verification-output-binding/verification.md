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
The new admission repair has not yet been loaded into the active service. Keep main runtime
source and target clone frozen while the current role runs. At a verified controlled idle
boundary, merge the reviewed commit, restart through the official script and verify Console
readiness before continuing the original Requirement's ordinary public flow. Do not deploy by
editing an active worktree or mixing old and new lazy imports in an executing Host.

Rollback uses the same controlled idle boundary and retains all old/new execution records,
approvals, claims and drafts. Reverting the guard cannot grant an admitted verification replay.
The original native Coder per-command capture limitation remains; this bounded repair secures
the existing independent verification receipts rather than claiming a new trusted command channel.
