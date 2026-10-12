# 2026-10-12 production fault retirement and read-only replacement

## Authorized scope

The user requested verification and safe replacement of the faulted ASE service, recovery of
frontend reading, and a report of repairs and K1 readiness. K1 delivery must remain paused.
No Requirement approval, RESUME/HANDLE action, model invocation, Coder/QA/Reviewer dispatch,
workspace rebase, direct SQL repair or newly created Requirement is authorized by this maintenance.

## Verified maintenance

The old Host PID 802 was frozen under the user's earlier explicit permission. The production
`prepare` command verified the original REFUSED lifecycle, kernel birth
`darwin-time:1791788657:752332`, executable, frozen state and supervisor PID 894. The exact plan
was `e884bab40bbfc2ee940de2c07b6032cb900c434227d261977a8f46da34d0f47b`.

The official `execute --confirm-fault-retirement` action finished at
2026-10-12T10:35:22.122625Z. It terminated the exact supervisor and frozen Host, verified absence,
and preserved the complete original lifecycle and log. Receipt
`311c018e32f0f70e3a7900949128f2fafc07bd1fd8a9c59077bfb4d9239a89c8` records confirmed SIGKILL to
the exact Host and successor_mode=inspection. Historical execution outcome and scope completeness
remain UNKNOWN; original REFUSED never became READY.

The archived log is 10,176,428,176 bytes, SHA-256
`5b6b6f559ecaceaa4a967b30d030d83cc00ba9195b1125146f887ad3e192e31d`. It was moved on the same
filesystem rather than copied or truncated. All maintenance records reside below the existing
service state directory at `console-fault-retirements/<plan_sha256>` with private permissions.

The normal supported service script then started PID 37223. Its actual Console API declares
mode=inspection, delivery_ready=false, supported_actions=[], operation contract 8. No TeamHost,
dispatcher, index worker or delivery executor is constructed. Lifecycle RUNNING means this reader
is running, not that delivery is enabled.

## Existing data treatment

Read-only before/after snapshots matched for all five tables: 196 Tasks, 734 StateEvents,
97 WorkItems, 112 claims, 460 queue events. All 9,287 files under Team/Projects and all 2,610
entries in the preserved Coder checkout matched byte fingerprints. Coder HEAD, branch,
status, staged diff and unstaged binary diff matched. No SQL migration or factual rewrite.

K1 Task `task_recovery_45588301d1b35b02f44762650b6195e4` remains IMPLEMENTING, revision 2,
attempt 3, with WorkItem `work_b6d99b642d61ff305b09dcde1aac04050ce768cab597e94eb49afdaa7d7e86f9`
WAITING_DEPENDENCY and zero ACTIVE claims. Preserved checkout HEAD remains f91f33a with the
existing draft. Requirement and all prior approvals/budgets/UNKNOWN history remain intact.

The task and queue are different state machines: IMPLEMENTING is the retained delivery checkpoint,
not evidence of current execution. This maintenance does not certify that the existing K1 can
finish delivery. Future authorized continuation must re-check the existing wait, source/progress
and approval facts, then pass independent QA and Review.

## Real frontend finding during deployment

The real Python read side successfully read the selected project summary in 3.866s and exact K1
detail in 6.75s (221,235 serialized bytes). HTTP subsequently returned summary 200, but Chrome
still displayed read failure. Real `to_wire` omits None fields; JS Task identity checks normalized
the resource side to null but compared against undefined source fields. Historical empty Task
identities and candidate-verification records therefore caused the whole valid summary to fail.
The same asymmetry existed in full Task detail verification. This is a frontend contract defect,
not missing database records; its separate minimal regression fix must preserve wrong nonempty
identity rejection. API success alone is not frontend acceptance.

All 80 K1 Operation summaries were verified across two pages with stable inventory and no active
Operations. Exact latest Operation, model-call history and preparation-progress GETs returned 200.
The first post-start memory sample was 758,928 KiB RSS; new log remained 198 bytes. These are bounded
observations, not proof of long-term memory stability or a conclusive original CPython fault cause.

## Final deployed frontend acceptance

`8f03293` integrates the independently reviewed nullable-wire correction. The current inspection
instance PID 37223 completed the normal controlled READY/stop path and was replaced with PID 62729,
still in inspection mode. This exercised ordinary controlled restart without unpausing delivery.

Two sequential real Chrome sessions completed: exact K1 Requirement and exact child Task. Both
returned summary/detail HTTP 200, displayed `完整正文与历史已读取`, reported detail status=ready,
teamReadIssue=null, mode=inspection, delivery_ready=false, supported_actions=[] and the maintenance
notice. No JavaScript error, request failure, external request or mutation attempt was observed.
Total browser checks were 13.3s and 18.5s respectively, including startup, Operations, summary and
full detail. This is successful complete reading, not a claim of instantaneous rendering.

Browser /app.js SHA-256 exactly matched checkout bytes:
`5702cc3406808ccad0ad0ac8474e5165bb00da88fff98f7c3d6d395830b44d74`.
The Task check's first temporary harness attempt used nonexistent page=`tasks`; it was corrected
to the application's existing requests navigation and re-run successfully. This was a test-script
mistake, not another production defect. Old failed Operation messages are preserved historical facts,
not newly executed operations.

After final restart and both browser checks, another read-only snapshot matched the original
five database tables, all Team/Project files and all Coder files/HEAD/branch/diffs exactly.
No K1 facts changed throughout deployment and verification.

## Workspace organization

All 51 original `code/ase-*` directories moved to `code/ai-workspace/`: 48 Git worktrees through
`git worktree move`, 3 standalone clones through same-filesystem rename. HEAD, branch, all
untracked path names, staged/unstaged binary diffs matched before/after. Zero original `ase-*`
directories remain at code root. These directories are isolated platform repair/review checkouts,
not business projects or duplicate K1 requirements. Main checkout and production `.ase/worktrees`
were not moved. Nine moved directories have old virtual environments; use the main interpreter
with explicit PYTHONPATH or recreate those environments because script shebangs may retain paths.

## Validation and rollback

Merged code at 0e7b946 passed 82 focused tests across fault retirement, inspection composition,
real marker integration, lifecycle and OS inspection. The independent reviewer separately ran
11 real OS boundary tests. See the two task validation records for earlier incremental and Chrome
checks. Full tests were not run, as requested by the user.

Rollback must first use controlled stop on the current inspection service and retain the private
archive and persistent marker. Do not delete the marker, rewrite REFUSED, or launch an older normal
writer to restore UI. Returning to normal delivery requires separate explicit maintenance completion
and user authorization; it is not an action performed or proven by this report.
