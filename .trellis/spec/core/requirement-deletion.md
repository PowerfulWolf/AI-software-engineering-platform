# 产品需求删除与工程历史保全

## Scope / Trigger

适用于 `DeleteRequirement`、Console `DELETE_REQUIREMENT`、Project reader 及删除后重新创建。
删除是产品目录的永久 tombstone，不是关闭、重启、销毁 dirty worktree 或覆盖已封存历史。
生产入口必须核验已显示的 Project / Requirement / checkpoint 精确身份，并证明工程执行停止。

## Signatures

```text
DeleteRequirement(delivery_id, expected_checkpoint_sha256, submitted_at)
JointDeliveryService.delete_requirement(command) -> JointDeliveryResult
RequirementDeletionGuard.protect(checkpoint) -> AbstractContextManager[None]
ProductionRequirementDeletionGuard(project, queue, dsn)
RequirementRetirementStore.retire(checkpoint, reason="deleted", retired_at=...)
RequirementRetirementStore.require_native_active(delivery_id, journal) -> None
ConsoleIntent(action="DELETE_REQUIREMENT", project_id, delivery_id, expected_checkpoint_sha256)
```

Console 的现有 Operation journal 先封存用户意图，再由 Manager adapter 调用服务；不新增第二套
HTTP 删除或目录清理入口。tombstone 继续使用 `requirement-retirement.schema.json`，旧 digest
与原历史保持可读。checkpoint digest 已绑定 scope，不另设可覆盖 scope 的删除参数。

## Contracts

- 支持未批准的 Product draft，以及已停止的 `BLOCKED` / `CLOSED`。不允许删除正在交付的需求。
- 在现有 Requirement operation lock 内验证完整 journal、owner 和 expected digest；同一精确
  deleted checkpoint 重放成功且不改 tombstone 时间/字节，其他 digest 或 replaced 记录拒绝。
- 有 Task 的历史必须配置 production deletion guard；guard 遍历所有联合及原生子交付历史，
  保留全部历史 Task，持有现有 `state/queue-worker-locks/<sha256(task_id)>.lock`，不清理代码。
- Task 必须是 `DONE/BLOCKED/FAILED`，queue steps 必须 `CLOSED`，无有效 Lease 且进程锁可独占。
  Task/queue facts 从 typed 端口与只读 SQL 获得，不构造 Task writer，不执行 DDL、不改 verdict。
  缺失、漂移、跨仓归属、live process、有效 lease、未结束 queue 都拒绝，不能靠 UI 隐藏处理。
- 新建同名、同scope需求派生新的 delivery identity；仍保留当前输入的幂等创建，永不调用
  `retirements.restore(old_id)`，不复用旧 Product approval / design / plan / Task /候选或预算。
- 已删 parent 的列表、计数、详情、child Tasks、Agent assignment 均从同一 retirement 事实过滤。
  Continue、Product approval、restart、知识审批和原生 child recovery 也必须拒绝 deleted parent；
  原 immutable audit 文件只能用于工程审计读取，不授予再次执行的能力。
- `require_native_active` 校验所有retirement的owner/current digest，并核对完整父历史children
  和未attach子交付的确定性派生identity。Host native Continue在构造recovery controller前调用；
  NativeRecoverySourceReader在读SQL前调用，shared `_parent`重复核验给Candidate/restart使用。
  matched retired parent抛中文`RequirementRetiredError`，不能跳过它并降为standalone恢复。

## Validation / Error Matrix

| 输入 | 行为 |
|---|---|
| exact idle BLOCKED/CLOSED | 写一次 tombstone，原 journal / Task / artifact / dirty代码不变 |
| 相同删除重放 | 返回原 checkpoint，原 tombstone 字节不变 |
| stale checkpoint / other Project | 拒绝，无 tombstone |
| live Worker lock /有效 Lease /未closed queue/非terminal Task | `RequirementDeletionRejected`，Console `REQUIREMENT_ACTIVE`，中文下一步 |
| deleted parent Continue/approval/restart | 拒绝，零新增模型调用 |
| 同名新建 | 新 identity + 原产品准备流程，旧 tombstone/history永久保留 |
| corrupted retirement/history | fail closed，不能用缺失数据冒充无活动 |

## Good / Base / Bad

Good：删除用户不再需要的两份已停止 K1，产品页无残留，审计保留，并且不新建/执行。
Base：尚未开始讨论的草稿删除，同一精确命令可安全重放。
Bad：同名create撤销tombstone、直接删除sidecar、只过滤列表而child仍可执行、改旧Task终态。

## Tests / Existing Data / Rollback

增量 `tests/manager/test_requirement_retirement.py`、`tests/manager/test_requirement_deletion.py`、
`tests/web_console/test_manager.py`、`tests/team_view/test_live.py` retirement case。
覆盖公开typed入口、实际process锁、历史owner与原生Task inventory、lease/queue/Task负向、
同名新identity、删除重放与旧审批保持；不跑全量。

存量两 K1 只能在空闲部署后，用当前 Project/ID/digest 提交正式 Console deletion Operation；
检查Operation成功、reader列表/详情/计数/child一致，以及原历史/hash不变。不得直接生产SQL写入、
删目录或清理dirty worktree。回滚代码需在空闲时进行，保留已删 retirement；旧版本同名create
会复活记录，应暂停create直到修复版本重新加载，不能把回滚作为撤销删除。
