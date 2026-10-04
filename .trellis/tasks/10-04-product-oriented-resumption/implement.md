# 实现与增量验证记录

## 已实现

- `InterruptionContinuationPolicy` 随普通生产 Task 冻结；旧 Task 缺字段不追溯授权。
- owned Codex runner 记录可校验 `NativeProcessStop`。无法确认进程组停止时不会继续模型调用。
- `WorkspaceMutationInventory` 双读观察 ignored 文件、模式和 symlink；合法首轮 Coder 文本草稿封存 immutable receipt，单次新 Run/claim admission 由 `NativeCoderContinuation` 校验。
- 中断 receipt、完整 inventory body、capture、原始 typed failure、预算和 Task intent 绑定；不伪造 CoderProgress，不在同一 Run dirty fallback。
- 产品视图把交付阶段、执行状态、责任方和等待原因分开，保留完整中断/QA/Review/返工历史；技术身份进入工程详情，lease 过期不冒称停机。
- 正式 `DELETE_REQUIREMENT` 入口已实现，部署后用于处理两个 K1：精确 scope/checkpoint、历史 Task/queue/lease 检查、幂等 tombstone；native/recovery 入口拒绝 retired parent。sealed 历史和旧 dirty worktree 保留。

## 增量验证

以下是独立的受影响用例组合，不将重叠数量相加成全仓测试总数：

- Codex CLI / owned execution / retry / runtime / production delivery / native continuation：最终组合 `115 passed`；最后预算错误分类调整后的 retry/runtime/delivery 定点 `30 passed`。
- receipt / store / native continuation 的独立只读复核：`69 passed`；记录 / Schema / native 定向组合 `73 passed`；最后预算/成功路径/重领/admission 定点 `22 passed`。
- Requirement retirement/deletion/Web Console/TeamHost/native recovery：`96 passed, 3 deselected`；隔离 MySQL 删除用例串行 `3 passed`。
- 联合交付 live MySQL 受影响用例串行 `3 passed`。修复测试 fixture 的 typed Manager 输出，未把共享数据库并行 reset 的无效失败作为发布结论。
- 新公开生产接线组合：`tests/manager/test_production_continuation.py`，`1 passed in 6.76s`。真实 TeamHost、dispatch/claim、owned process stop、receipt/admission、CandidateCommitSkill、QA 命令证据和独立 Reviewer；可控模型 runner，未调用真实模型。验证 attempt 2 使用原 Task/branch/worktree、不同 Run/Context/Lease，本地超时扣工作预算且无 provider transient 退款，最终 DONE。
- 产品/完整历史/live reader 的 Python 定向组合 `44 passed`；Node DOM `90` 项；Chrome 14 个受影响模块通过，产品状态和历史模块最后再次通过。
- 变更源码和新增公开接线测试 mypy、Ruff、format、`git diff --check`、continuation schema sync check 均通过。

未运行全量 test，留给用户按约定执行。真实生产需求未启动。

## 存量处置、部署与回滚

服务重启必须在提交推送后、无运行中 Operation/lease/process 时进行。两个 K1 只能通过正式产品删除入口退役，不能 SQL 改状态、删除目录、重开终态或清理 dirty worktree。回滚代码时保留 receipt/policy 的只读兼容读取和 Requirement tombstone；不要恢复旧需求身份或执行旧 unsafe plan。
