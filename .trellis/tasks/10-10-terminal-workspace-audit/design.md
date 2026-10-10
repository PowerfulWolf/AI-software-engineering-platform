# 签名与验证设计

`RecoveryWorkspaceSnapshot` 在 `workspace_records.py` 只依赖 domain/git 类型，不导入
`recovery.models`，允许 RecoveryPlan 引用它而不形成依赖环。scope显式包含 Team/Project/
Repository/native Requirement/dispatch。excluded_paths为精确sorted metadata，不保存正文。

`validate_terminal_workspace_snapshot(*, source, permissions, denied_paths, capture, facts,
observation) -> RecoveryWorkspaceSnapshot` 是纯事实校验；无shell/SQL调用。
`read_terminal_workspace_snapshot(config, environment, original, capture) -> snapshot | None`
在现有 Task process lock 内使用只读 consistent SQL snapshot 读取正式 store，观察完整
inventory 并前后重新核验；不得嵌套获取恢复提交外层已有的 MySQL global authority fence。
只读queue opener不得调用初始化Schema的普通MySqlRoleQueue构造。

Good：真实已停的现代失败，合法27文件完整，首次新增ignored环境文件只在旧现场留档。
Base：无policy旧Task返回None；无环境新增也绑定完整现代证明。
Bad：将Task.model_copy(status=IMPLEMENTING)传给旧stop校验器、凭租约/重启猜停止、忽略
全部hidden文件、清理 `.venv`、用扩大恢复范围审批给环境文件授权或复制进新Task。

## Composition and locking addendum

恢复提交的外层服务已持有 MySQL global authority fence；终态审计不会再次调用
`idle_task_scope` 或构造会初始化 schema 的 `MySqlRoleQueue`。helper 只在已有 Task
process lock 内打开一个 `REPEATABLE READ, READ ONLY` consistent SQL snapshot，读取
terminal Task/event、closed queue item、历史 claim/step/dispatch 和 accepted facts。
原 Task 已为 BLOCKED，读取期间不能合法 claim；审计前后重新读取 source、持久化事实、
完整 no-follow inventory、Git capture 与 process stop；任一 inode、事实或策略变化即拒绝。
这避免同一 MySQL authority 的嵌套锁死，也避免 read-side 为缺失锁创建文件。生产 helper
要求现有 regular private lock；旧 Task 不存在该 modern policy 时返回 `None` 保持历史兼容。

helper 可显式接收 `approved_permissions` 和 `scope_supplement`。原 request.permissions 不变；
补充必须绑定原 Task/revision/checkpoint、原权限与 denied digest、当前 approved capture base，
并由上层现有精确审批链授权；helper 再发现并比对 supplement，然后用补充后权限核验 patch。
`.venv` metadata 不得作为补充范围、cache、receipt 或 candidate。

Snapshot 时间锚点是 durable terminal event，不把观测时钟写入摘要；实际观测仍须在 terminal
event 之后。正式 claim row 与 CLAIMED event 的原始索引事实摘要也进入 claim_sha256；前后
读取拒绝 owner/state/time 变化。Raw Task/event/item/claim 标识、状态和索引列必须与 payload
相符，不能用 payload CLOSED 覆盖 raw RUNNING。

成功的已接纳 Coder progress 是已有独立契约：只有重新 NativeSourceReader 校验、实际 formal
final route 为 SUCCEEDED且其exact artifact等于该source的已接纳progress，再完成
require_stopped_progress和source/routes前后核验时，才返回None。FAILED路线即使存在prior
progress仍必须生成完整failure workspace snapshot；缺stop/outcome或未知执行不能降级None。

原 Task approved base不变；baseline.execution_base_ref只定义完整patch比较基线，实际Run
source绑定capture.source、原request、context和frozenstep。baseline场景二者可不同，不能强制
source==base；无baseline时仍要求原Run source==approved Task base。

原 native executor stop 与最终 outcome 的错误分类是两个独立事实：例如真实 TIMEOUT
停止后，保存完整现场可能由 POLICY_VIOLATION 结束。两者各自保留并由 invocation、最终
route 和 stop digest 分别绑定；不能用其中一个覆盖另一个。
