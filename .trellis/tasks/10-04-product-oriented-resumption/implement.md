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


## 生产发布与存量验收

- 主实现提交 `47003197eb31ecfd0ade0cd4cdf6f52db9351def` 已推送 main；目标 clone 干净 fast-forward 后，在无 active Operation 时重启，新 PID 66555，Console `delivery_ready=true`。
- 删除前封存两 K1 /其他 DONE 需求的精确 checkpoint、1743 个审计文件 SHA、23 个 dirty 文件 SHA/HEAD，以及31个历史Task、127条StateEvent、61个队列项、266条队列事件、68条claim只读快照。隔离测试库与生产DSN精确不同。
- 首次正式删除 `operation_7b5db7773de9d54c4131e372cc1de5e3` 安全拒绝 `REQUIREMENT_ACTIVE`。已关闭 K1 仍有3个旧 IMPLEMENTING Task及lease-expired RETRY_SCHEDULED队列。没有写tombstone或调用模型。
- 已补明确用户撤销需求的 typed cancellation/queue settlement：用户决定封存为 Schema-valid resolution receipt，完整历史进程锁、authority fence、exact Task/queue snapshot 和有效 Lease 检查后终止旧 Task/关闭旧队列。原终态/历史/草稿不改写。独立只读复核通过。
- 取消补充增量：新的 queue MySQL `17 passed in 1.90s`；真实公开删除取消+原有 guard MySQL 串行 `4 passed, 5 deselected in 0.89s`；取消/guard 非 MySQL `22 passed, 4 deselected`。三个变更源码标准 strict mypy、相关 Ruff/format/diffcheck通过。提交部署后记录成功Operation与前后校验。不会执行新需求。

- 取消补充提交 `38762ab3310fcea6ea50f8193696924ea25f0d93` 已推送/空闲部署，PID 74641。第一份 K1 正式删除成功：`operation_3173ddeb5955c209f104c97b564e5c6a`，29个历史Task的取消receipt已封存，只有3个原非终态Task新增取消状态事件，未调用模型。
- 删除后 public Team GET 的旧verification source过滤缺陷已补：完整retired parent/native历史+精确(repository_id,task_id)过滤，保留active missingSource拒绝并防全局Task身份复用。新public回归先红于503，最终新回归/身份冲突/原replanning负例 `5 passed in 37.00s`；相关其他4个live MySQL用例之前通过。旧负例仅迁移到history读取seam，拒绝断言未弱化。相关Ruff/format/mypy及独立只读复核通过。


## 最终发布与存量数据处置（2026-10-05）

只读过滤修复提交 `3653bcc` 已推送并部署，当前服务 PID 88817、`delivery_ready=true`。
两个精确需求均通过正式 DELETE_REQUIREMENT Operation 删除：

| 原需求 | Requirement ID | 成功 Operation |
| --- | --- | --- |
| 已关闭 K1 | delivery_multi_33d30fe0776a232e31617caa9e702b915dcb4c65 | operation_3173ddeb5955c209f104c97b564e5c6a |
| 阻塞的重建 K1 | delivery_multi_74df2af872dd99c7b3369341c6a663c707aebb97 | operation_06ab2060c1ed6146c6033c8a0b889b75 |

两个 Operation 都 SUCCEEDED/REQUIREMENT_DELETED，model-calls 均为空。本次代提交来自用户
明确删除两份需求的委托；初次 guard 拒绝的 Operation 也保留，不冒称模型自治审批。

- Team API 与真实 Chrome 页面均只有原有“增加配置应用按钮”需求，保持 DONE 和原 checkpoint `fc401e5a2d4edaec3bcd7764f477a1ccdc699c7ee221a63552c67902be60e3a3`；Project count 3→1。
- 已删 parent、child、旧验证及相关 Agent 引用消失；native Continue 的只读 retirement gate 对两份子交付均明确拒绝。未 POST Continue 或新业务执行。
- 前后核验 1743 个原封存文件、23 个 dirty 文件和原 HEAD 完全相同。原 127 条 StateEvent、266 条 queue event 逐条不变，68 条 claim 不变，所有旧 terminal Task 快照/revision 不变。
- 仅3个旧 IMPLEMENTING Task 追加用户取消事件成为 BLOCKED，revision 各+1；对应3个暂停队列增加 REQUIREMENT_CANCELLED 并 CLOSED。两个新的 cancellation receipt 与2条 retirement 记录封存，旧3条 retirement 保持不变。
- 新增生产 Operation 仅为3次 DELETE（1次安全拒绝、2次成功），均零模型调用；无新 Requirement、Assignment、Lease、Run或业务交付。
- 只读校验结果保存在 `/tmp/ase-k1-deletion-{before,after}.json`，SQL before审计与执行Operation记录同前缀文件；临时审计文件0600、不提交仓库。不通过生产SQL补丁改状态，不删除dirty工作区。

最终增量命令与结果：

```sh
.venv/bin/pytest -q tests/work_queue/test_requirement_queue_cancellation.py
# 17 passed
.venv/bin/pytest -q tests/manager/test_requirement_cancellation.py::test_public_delete_real_queue_settles_nonterminal_and_retains_immutable_history tests/manager/test_requirement_deletion.py -m mysql
# 4 passed, 5 deselected
.venv/bin/pytest -q tests/team_view/test_deleted_verifications.py tests/team_view/test_live.py::test_joint_reader_preserves_child_ownership_through_integration_replanning
# 5 passed
```

上述 MySQL 均串行使用核验过的隔离测试DSN。生产Task/queue的写入来自已批准删除意图触发的
应用服务和原有审计存储。全量 tests 按用户约定未运行；不宣称零 Bug 或通用崩溃恢复。

回滚须在服务空闲时进行，且保留 receipt/policy 兼容读取、已删需求及旧verification过滤、
同名create不复活tombstone的修复。已删身份不能复活、恢复旧批准或执行旧unsafe plan；工程
历史/草稿只能用于审计。后续仅在用户明确要求后新建业务需求并重新交付。
