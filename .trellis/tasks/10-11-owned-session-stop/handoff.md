# Maintenance handoff — pending independent review

Branch `fix/owned-session-stop`, isolated worktree
`/Users/zhangjunshuai/workspace/code/ase-owned-session-stop`, base
`e4023c47b7194513a3ab3bb1b05951f89baf58f5`. No commit, main integration, service
deployment, ASE operation or historical fact change has been made by this worker.

## Result

The original PGID-only stop gap is replaced by one actual-Popen capability covering
the complete original SID and already observed kernel births. Same-SID peers changing
PGID and closing pipes stop before publication; denied/incomplete identity observation
or a known setsid escape remains unknown. New native stop proof is optional/versioned;
all ten schemas agree and absent/null legacy bytes/digests remain unchanged.

The Host registry also retains `finalizing` observations through actual command
evidence put, outer run manifest seal and verification receipt put. Bounded nested
scopes and explicit proxy worker propagation avoid early clear. Put/seal failure,
missing/duplicate/late confirmation and execution after confirmation latch uncertainty.
Capture failures retain no raw exception traceback/caller payload.

## Complete inventory

- New production module: `src/ai_software_engineer/owned_sessions.py`.
- Ownership/controller integration: `owned_processes.py`, `agents/codex_cli.py`,
  `agents/execution.py`, `execution.py`, `orchestration/continuation.py`.
- Actual durable boundaries: `evidence/capture.py`, `recovery/verification_execution.py`,
  `manager/python_mysql_execution.py`, `manager/python_mysql_proxy.py`.
- New generator: `scripts/sync-owned-session-schemas.py`.
- Ten stop embeddings: `completed-coder-output-unavailable`, `console-operation`,
  `execution-baseline-plan`, `execution-baseline-queue-consumption`, `execution-capture`,
  `execution-continuation`, `knowledge-execution-record`, `knowledge-invocation-outcome`,
  `rejected-coder-output-checkpoint`, `structured-execution-observation` schema JSON files.
- New tests: `tests/execution/test_owned_session_stop.py`, `test_owned_session_inspection.py`,
  `test_owned_record_finalization.py`, `tests/contracts/test_owned_session_stop_schema.py`.
- Mock fixture adaptation only: `tests/agents/test_structured_observation.py`,
  `tests/recovery/test_native_ui.py`.
- New executable spec `core/owned-session-stop.md`; updates to core controlled restart,
  engineering continuation and index, recovery thinking guide and architecture contracts.
- This task directory: PRD, design, task metadata, bug analysis, verification and handoff.

`git diff --stat` excludes untracked new files. Review `git status --short` and
`git ls-files --others --exclude-standard` as well. Exact allowlist is in `task.json`.

## Validation

Final dedicated **46 passed**; existing native/executor **120 passed, 1 deselected**;
evidence/continuation **81 passed**; mocked native-UI/verification **38 passed,
6 deselected**. Ruff format/check and scoped strict mypy **17 files passed**;
diff/allowlist checks passed. Commands, red failures and limitations are recorded
in `verification.md`. Only incremental tests ran; no MySQL tests or models ran.

## 存量数据处置

无需改库。旧 NativeProcessStop 继续使用原 leader/group 范围与原 digest；缺失旧事实
不补造、不加强，不修改 Task/WorkItem/Operation、预算、审批或原执行结果。当前 K1 的
保留现场和交付状态未触碰。根 agent 独立复核并在当前执行实际结束、记录已保存后，
通过已有受控停止/重启协议部署修复；随后仍按精确授权的原需求继续路径交付，不因代码
部署自动 rebase、审批或新建需求。

## Limits and rollback

This is bounded owned-session observation, not atomic kernel process-tree containment.
Unobserved setsid escape remains outside proof scope. Real Darwin execution is tested;
Linux runtime and MySQL consumers are not runtime-validated here. Missing ownership
captured before reap fails closed rather than retroactively reconstructing a proof.

Rollback only after verified controlled stop and before new invocations. Preserve
proof-bearing records and complete original history. A reverted reader must support
the new optional field before reading new records; never strip proof bytes or rewrite
their digests. Root owns independent approval, integration/commit and deployment.
