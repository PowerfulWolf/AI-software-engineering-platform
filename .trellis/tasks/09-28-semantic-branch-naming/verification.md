# Verification — semantic branch naming

Date: 2026-09-28. Resumed from the existing implementation and the user's checkpoint:
60 tests passed; two distinct-requirement fixtures had reused one semantic name and were
correctly rejected as collisions. Their fixture changes were already present on resumption.
This report records commands run in the resumed session, not an independent QA/Review verdict.
The initial verification phase did not run live models, restart production, commit or push.
After receiving the results, the user explicitly requested task completion, commit and push.
The engineering record is therefore closed; production deployment remains outside this submission.

## Confirmed contract

- New production Product output supplies `ai/feature/<business-slug>` or
  `ai/bugfix/<problem-slug>`. Approval freezes the name into ProductSpec and Task.
- Same-Task continuation keeps the branch. Independent recovery/remediation keeps the
  original kind and derives a distinct purpose-qualified name from its immediate source.
- Trusted Task bindings, Git collision/ownership checks and independent detached QA/Reviewer
  worktrees remain enforced. Candidate display resolves the exact frozen ref at the candidate.
- Historical absent fields stay omitted; legacy branches, immutable bytes, digests and
  approvals are preserved. Embedded JSON Schemas carry the new optional fields.

## Checks run

| Command | Result |
| --- | --- |
| `.venv/bin/pytest -q --tb=short tests/git/test_semantic_branches.py tests/manager/test_branch_naming.py` | Final rerun: 31 passed; real Git, ownership/collision, capture, approval, legacy and schema checks |
| `.venv/bin/pytest -q --tb=short tests/git tests/role_workspace tests/recovery/test_models.py tests/recovery/test_cli.py tests/manager/test_branch_naming.py` | 171 passed after adding the clean-restoration ownership guard; final extra cleanup-failure case checked in the next row |
| `.venv/bin/pytest -q --tb=short tests/git/test_semantic_branches.py` | 25 passed including six new removal/ownership cases |
| `.venv/bin/pytest -q -m 'not mysql' --tb=short` | 1992 passed, 10 opt-in skipped, 101 MySQL deselected; two CLI fixture failures and seven sandbox socket setup errors addressed below |
| `.venv/bin/pytest -q --tb=short tests/recovery/test_cli.py tests/recovery/test_models.py tests/manager/test_branch_naming.py tests/web_console/test_manager.py` | 75 passed after repairing the capture fixture |
| `.venv/bin/pytest -q --tb=short tests/team_view/test_live.py -m 'not mysql'` | 21 passed, 6 deselected after approved execution outside the socket-restricted sandbox |
| `.venv/bin/pytest -q --tb=short tests/e2e/test_joint_delivery.py tests/e2e/test_project_revision_preparation.py tests/recovery/test_execution.py tests/recovery/test_resume.py -m mysql` | 22 passed, 1 deselected; serial dedicated-test-database run, 1216.78s |
| `.venv/bin/pytest -q --tb=short tests/recovery/test_native.py::test_nontransient_invalid_output_is_a_recoverable_native_source` | 1 passed, 6.87s; fresh-process real Host cleanup/restoration check after the final ownership guard |
| `node --test tests/team_view/*.test.cjs` | 61 passed |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check src tests` | 483 files formatted |
| `.venv/bin/mypy src tests` | Passed, 488 source files |
| `uv build --offline` | sdist and wheel built successfully |
| `git diff --check` | Passed |

The broad non-MySQL run preceded the final clean-restoration guard; the Git/role/recovery
focused suite covers that production change. The two failing CLI parameters changed
`CapturedChanges.branch_name` with `model_copy`
but retained the old capture digest. The fixture now changes the in-process worktree fact
and rebuilds the sealed capture with `CapturedChanges.from_capture`. Production integrity
validation was not changed. All non-MySQL failures/errors from the broad run have passed
in the focused reruns; the full suite was not rerun after this fixture-only correction.
Two existing Starlette/httpx/AnyIO deprecation warnings remain.

The first MySQL invocation was denied by the sandbox before connecting. The rerun uses the
existing `ASE_TEST_MYSQL_DSN`; `tests/mysql_safety.py` rejects non-test database names before
fixtures can run. No other MySQL pytest process was active when the serial run started.
The 22-case process began before the final ownership guard was added. A separate fresh-process
native Host check passed afterward, so the new removal/restore composition is exercised against MySQL
without running two fixture cleanup processes against the same test database.

## Cross-layer inspection

- Followed Product → approval → Task/dispatch → trusted Git manager → capture → approved
  recovery → successor Task and exact-ref read model. Branch names do not grant ownership.
- Other Git manager construction sites are detached requirement/integration workspaces or
  read-only candidate inspection; they do not create unbound semantic Coder branches.
- New Product producers require a name. Legacy omission is confined to historical reads
  and the trusted deterministic projection of already-approved joint Product documents.
- Existing README/document-organization changes were preserved. This resumed session adds
  the CLI fixture correction, the clean-restoration ownership guard/tests, failure-mode
  guidance and task verification records.
- Submission inspection confirmed that the README changes describe this branch contract.
  The two migration-manifest corrections retain the in-flight branch documentation as
  `working_tree_at_migration`; both source and destination hashes match the preserved
  migration snapshots. Historical migration hashes are not recomputed from today's documents.

## Bug analysis — clean restoration ownership

1. **Root cause (C/D/E)**: creation gained semantic-name collision checks, but clean restoration
   retained the old assumption that a branch name itself contained a unique Task ID. The
   original tests covered same-Task restoration and live-worktree collisions, not a cleaned
   unrelated worktree with the same SHA.
2. **Reproduction**: a temporary real Git probe created Task A's semantic branch, removed its
   clean worktree, and gave Task B the same name. `create` rejected it but `restore_clean_coder`
   succeeded. The regression failed first with `DID NOT RAISE WorktreeIdentityDrift`.
3. **Prevention**: semantic cleanup now durably records exact ownership before Git removes
   registration. Restoration requires that receipt as well as existing ref/revision guards;
   malformed receipt persistence preserves the source worktree. No branch/SHA-only adoption.
4. **Systematic check**: tests cover process restart, repeated same-owner cleanup/restoration,
   missing/nonempty/symlink receipts, cross-Task and cross-layout copies, and cleanup failure.
   Existing legacy restoration, capture/seed and detached-verifier tests continue to pass.
5. **Knowledge capture**: the executable contract and error matrix are in
   `.trellis/spec/core/branch-naming.md`; Git architecture and this task's design are updated.
   This repository has no generated spec template mirror. The initial verification phase
   kept changes uncommitted; the user's subsequent instruction explicitly authorizes submission.

## 存量数据处置

无需改库或重命名分支：这是新需求分支意图及跨层传递的增量契约，不是已持久化历史损坏。
本轮只操作临时测试仓库和隔离测试数据库，没有修改生产 Requirement、Task、Operation、
审批、候选或队列事实。缺少新字段的旧需求继续使用原分支和原摘要。
本次新增语义分支代码尚未部署，所以无需为生产补清理标记。若存在人工试验版创建且已删除工作树、
又缺少精确标记的语义分支，不得只凭同名/SHA 补造标记；保留旧分支，另立并批准新需求处理。

在后续获准部署兼容代码后，现有需求按原流程继续：

1. 在 Console 打开原需求，读取当前 checkpoint、阻塞原因与待审批内容。
2. 普通可继续状态使用原需求的“继续”；历史 Task 不补写语义分支名。
3. 若需中断恢复，先提案并检查 source Task、捕获文件、目标基线和目标分支，再批准精确
   recovery plan digest；有范围补充时先完成独立的精确范围审批。
4. 若语义恢复目标已占用，用 `ase recovery propose ... --target-branch-name
   ai/feature/<更具体的恢复短名>`（原类型为 bugfix 时保留 bugfix）重新提案并批准新摘要。
   不移动旧 ref，不复用另一 Task 的工作树。已派发的普通需求不能原地改名，应新建名称更
   具体、另行批准的需求；原历史保留。

## Limits and rollback

- Automated checks use fake/scripted models with real Git and, where marked, MySQL. Live
  model naming quality and a deployed browser flow are not claimed; opt-in GUI/toolchain
  probes remain skipped. No independent QA/Reviewer approval is fabricated.
- A long successor name or occupied target fails closed. Operator recovery may require a
  more specific explicitly approved target name; no truncation or random suffix is added.
- No new production records were generated by this task. Before rollout, rollback means
  reverting only this task's code/schema/test/spec changes while preserving unrelated work.
  After semantic records exist, retain new-field read compatibility; do not roll back to
  a recovery implementation that only reconstructs legacy names. Never delete branches,
  candidates, approvals or evidence as part of rollback.
- Local implementation and verification are finished. Following the user's explicit completion
  and submission instruction, engineering-task status is `completed / verified`. This records
  task closure and the reported automated evidence; it does not invent manual testing,
  independent role verdicts or a production rollout.
