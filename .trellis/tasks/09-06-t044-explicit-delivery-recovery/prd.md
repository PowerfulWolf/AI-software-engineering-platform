# T044 Explicit recovery after provider interruption

## Goal
Continue an interrupted delivery from preserved Coder work and approved upstream facts without
spending shared model quota regenerating Product, Design and Plan. User approved this direction and
reported 57% shared quota remaining. No new live model invocation during implementation/tests.

## Known facts
- Round3 parent/child/Task are terminal BLOCKED; the Coder branch has no new commit, but its
  isolated worktree retains 15 modified tracked files. No implementation artifact/QA/Review exists.
- Source main includes platform diagnostic fixes; user previously required requirement branch rebase
  on repaired main. Old approval/profile/baseline hashes must never be silently rewritten.
- Existing run recovery accepts only clean worktrees; same-run route replay preserves failed result.
- Existing terminal tasks cannot be restarted; independent role/candidate/evidence gates remain mandatory.

## Requirements
- Explicit human-authorized recovery, referencing exact failed checkpoint and frozen work snapshot.
- New execution identity linked to prior failure; never clear counters or mutate terminal history.
- Reuse approved Product/Design/Plan only through verified explicit lineage, not inferred approval.
- Preserve original dirty worktree; snapshot and reapply only authorized code changes to a fresh worktree.
- Any base update, patch conflict, path/symlink/secret mismatch or upstream drift fails closed.
- Coder must finish/commit/report; fresh QA and Reviewer validate the resulting candidate.
- No merge, push, deployment, arbitrary dirty-worktree adoption or bypass of role policies.

## Acceptance / scope under investigation
- Pure contracts and fake/real-Git tests before live provider calls.
- Exact replay is idempotent; changed source/checkpoint/snapshot must be rejected.
- Clean/dirty/committed partial work, conflicts, unavailable model and second interruption considered.
- v0.1 scope to converge after code research: recovery plan/approval seam, new Task mapping, branch seed
  capture and production entry. No generalized DAG, vector store or shared agent memory.

## Decision / bounded increments
User approved continuing the proposed recovery direction. No additional product choice is needed for
its read-only foundation. Keep T044 open until an authorized production recovery entry is usable.

- Same-Task retry was rejected: terminal history and failed run replay are immutable.
- Restarting Product/Design/Plan repeats paid work and discards interrupted Coder output.
- Chosen: linked recovery execution. First implement source capture; next durable authorization,
  carry-forward lineage/new base, fresh dispatch and bound snapshot seed.

### Increment A acceptance
- [x] Real Git captures staged/unstaged modifications without source/index/ref writes.
- [x] Exact identity, HEAD, file hashes, patch and index digest determine capture identity.
- [x] Revalidation rejects byte/index/HEAD/payload drift, respecting read/write/deny policy.
- [x] Unsupported changes, binary/secret/symlink/FIFO/oversized files fail closed; no live model calls.
- [x] Regression, Ruff, strict Mypy, lock/build and executable docs pass before commit.

Increment A supports only modifications to existing regular UTF-8 files. Added/deleted/renamed files,
partial commits and index-only changes are explicitly unsupported, not silently lost. The capture is
an in-process repository fact like WorktreeRef, not a wire Schema or persisted Artifact. Storage,
CLI/new Task/patch application are **not** claimed as implemented by this increment.

### Allowed paths / validation / rollback
`src/ai_software_engineer/git/**`, `tests/git/**`, `docs/git-worktree.md`,
`.trellis/spec/core/{index,delivery-recovery}.md`, `AGENTS.md`, this task directory and archive.
Validate: `.venv/bin/pytest`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`,
`.venv/bin/mypy`, `uv lock --check`, `uv build --offline`, `git diff --check`.
Rollback: revert isolated platform commit; no database/runtime or original worktree migration.

Future cases: process-loss replay; second interruption; new baseline/conflict; multi-directory child
lineage; original failure and human-intervention attribution in evaluation.

## Increment B scope and acceptance

Allowed paths extend to `src/ai_software_engineer/recovery/**`, `tests/recovery/**`,
`schemas/delivery-recovery.schema.json`, `docs/contracts.md`, recovery spec, task and archive files.
No target repository, original Coder checkout, live Task/checkpoint or approval records may be edited.

- [x] Typed plan/capture/decision contract and wire schema reject malformed, secret or mismatched input.
- [x] Persist immutable scoped plans and decisions outside code; read-only reopening does not initialize.
- [x] Exact decision replay survives restart with no repeated verifier calls; current drift still blocks execution.
- [x] Real temporary Git round-trip, concurrent first-winner, corruption, symlink/FIFO, root/scope replacement,
  private modes, short writes and interrupted publication have regression tests.
- [x] Full regression and release checks recorded before committing this increment.

Production native-fact and human-channel adapters remain unimplemented. Test fixtures are explicitly fake,
not evidence of real human approval or a successful platform delivery. T044 remains in progress.

## Increment A validation
2026-09-06: 23 capture tests; full regression **800 passed /139.05s**, including the dedicated local
MySQL test database (not self-iteration business data). Ruff/format, Mypy (258 files), offline lock,
sdist/wheel and diff-check passed. Build output used temporary directories after the repo `dist/`
write was denied by sandbox. Actual preserved Coder: 15 files/19,749 patch bytes successfully captured
and revalidated in memory with original permissions; index bytes and HEAD unchanged. No live models,
durable recovery receipt, new Task, candidate, QA or Review. T044 remains in progress.

## Increment B validation
2026-09-07: 42 new recovery tests; full regression **842 passed /81.74s**, including only the dedicated
MySQL test database. Ruff/format (482 files), strict Mypy (267 files), offline lock and sdist/wheel build,
diff-check passed. Real temporary Git verifies source bytes/HEAD preservation and rejects post-approval
drift. No live model calls, production recovery records, new Tasks, target edits, candidate or QA/Review.
Source platform changes are Astra's implementation, not autonomous requirement delivery.

## Increment C1 acceptance

Scope extends to `recovery/native.py`, `tests/recovery/test_native.py` and read-only constructor/write
guards in `context/store.py`, `product/store.py`, `design/store.py`, `planning/store.py`,
`project_manager/store.py`; task, recovery spec, contracts and archive docs are updated together.

- [x] Real original Task/dispatch/events + approved native stage chain resolved through read-only stores.
- [x] Joint parent and delegated approval lineage discovered, not caller-optional.
- [x] Failed Coder route/context/permissions bound to exact Task/base/attempt; corrupted/missing records reject.
- [x] Single/joint real Git/MySQL offline fixtures and store no-initialization/write rejection checks pass.
- [x] Read-only inspection of actual round3 resolves original BLOCKED/revision3 and exact known parent/child.
- [x] Full regression/build/lint/type checks recorded before local commit.

This is original-source inspection only. Fresh target preparation/rules, explicit carry-forward,
human recovery entry, fresh Task/dispatch/seed and actual Coder→QA→Reviewer remain unimplemented.

C1 validation 2026-09-07: 850 passed /84.30s, including dedicated MySQL tests; Ruff/format (485 files),
strict Mypy (269 files), offline lock/build and diff-check passed. Actual round3 source inspection:
Task digest fd8d42f0ed08ece74081265e9124b375ea6affa24eff9141c610865982c7c58b, child b67e1691,
parent 617b6514, original base 68f8f8c, 22 write allowlist entries /13 denies. Zero real model calls,
business writes, requirement commits, QA/Review or GitHub push.

## Increment C2 acceptance

Scope: `git/worktree.py`, package export, `tests/git/test_seed.py`, recovery spec, Git docs,
this task directory and archive. No original requirement worktree or business records are edited.

- [x] Seed captured existing-file edits into a different Task's clean Coder attempt 1.
- [x] Verify source capture, both path policies, exact identities and descendant target baseline.
- [x] Isolated-index three-way preflight rejects conflicts without changing target files/index.
- [x] Preserve source and post-apply failure evidence; reject dirty replay and merge-rule changes.
- [x] Repository-only offline tests; no model calls, candidate or production recovery admission.

T044 remains open: new target preparation/carry-forward and authorized production execution are not
implemented by this repository operation. Rollback is an isolated source commit, no migration.

## Increment C3 acceptance

Scope extends to `recovery/{current,task,native}.py`, shared `project_manager/production_rules.py`
and Host callsites, `tests/recovery/test_current.py`, spec/contracts/task/archive. No real requirement
checkout or business records modified.

- [x] Concrete native source + current target verifier for existing recovery authorization service.
- [x] Shared Host rules, versioned preparation/profile/binding, clean descendant Git base and capture checks.
- [x] Approved recovery produces deterministic in-memory NEW Task/rebound Request, original approval retained.
- [x] Missing approval/environment and stale code/knowledge/policy/records reject without hidden writes.
- [x] Full regression/release checks recorded before local commit.

Remaining production work: seal carry-forward/Task draft with fresh dispatch and execution receipt,
human recovery CLI, seed receipt/provider admission, then real Coder/QA/Reviewer delivery. No draft
may overwrite original READY Request or bypass execution gates.

C3 validation: 870 passed /140.55s; Ruff/format493files, Mypy274files, offline lock/build and
diff-check passed. Actual original-base read-only gate passed: BLOCKED/revision3, capture955b3247,
15 files, same joint parent, no persisted plan/Task/model. This is not approval of a new base.

## Increment D1 acceptance

Scope: `recovery/{records,sealing,store}.py`, `schemas/recovery-task-record.schema.json`,
`tests/recovery/{test_task_record,test_current}.py`, spec/contracts/task/archive.

- [x] Persist exact approved Task/rebound Request as one immutable scoped record.
- [x] Integrity/schema/plan/authorization/identity validation and sensitive-text rejection.
- [x] Reopen/exact replay, changed-content conflict and current-facts execution revalidation.
- [x] Final targeted/full regression and release checks before commit.

No real business record, DB Task, resource allocation or Agent run. No migration required; generic
Task execution must not consume this input as a dispatch receipt.

D1 validation: recovery suite61 passed /46.65s; final full879 passed /153.94s after fixing missing
Schema registry `$id/$schema`. Ruff/format497files, Mypy277files, offline lock/build and diff-check
passed. No live models or business records; dedicated test database only.
