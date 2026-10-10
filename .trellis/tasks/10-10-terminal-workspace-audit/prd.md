# 终态 Coder 工作区完整核验

## 目标与范围

已有现代 Task 在真实 Coder 失败后进入 BLOCKED；原工作区可能同时包含合法业务进度与
本轮首次创建的 ignored `.venv` 文件。普通 Git patch 看不到后者，恢复不能据此宣称
完整现场合法，也不能删除旧现场、将 `.venv` 扩成缓存能力或重置终态 Task。

新增 typed 完整工作区 audit。只有既有 start/stop、invocation outcome、route、原 claim/
step、精确 Task/event/context/source/policy 证明完整，现有 Task process lock 已持有、只读
consistent SQL 确认原 Task terminal 且全部 queue item CLOSED、当前原进程组已停止时，
才观察并封存完整 final inventory。业务 patch 原权限和完整捕获保持；仅本轮新增 ignored
`.venv/` 文件/目录内的符号链接（不访问目标）留原现场单独列 metadata，
不复制、执行、候选化或用于接续 receipt。缺 continuation policy 的 legacy Task 保持兼容。

## 验收

- 绑定 native Requirement（不将 joint parent 当作 native ID）、Task/Run/context/完整工作区。
- 不重写 Task；明确检查 terminal revision = start revision + 1，真实 start→stop→BLOCKED。
- 绑定 latest execution baseline，精确完整 capture 与所有继承 dirty 文件。
- 未停止/无锁/活跃claim、缺stop/outcome、scope/request/context/policy/claim/step漂移拒绝。
- 未知 hidden/ignored、非 `.venv` 未授权变化、已有 `.venv` 条目、tracked或未ignored
  环境条目拒绝；`.venv` 符号链接只观测 metadata，不follow。
- 完整 inventory、stop 和所有持久化事实前后重读一致，不写 SQL/历史/工作区。
- 有精确 scope supplement 时只使用既有上层批准后的补充权限核验业务 patch；不改原 request。
- snapshot 时间锚点取 durable terminal event，重复观测不因实时时钟产生审批摘要漂移。

## 数据语义、验证与回滚

启动 inventory 记录文件与链接，不记录空目录。因此这里只证明“启动前无任何 `.venv`
条目/文件”，不声称空目录不存在，不补造旧事实。新增 snapshot 是明确审批计划的证据，
不是自动批准或清理。存量历史/失败/verdict不迁移；root另行接入公开恢复路径和schema/UI。
本模块不操作生产、不审批、不重启、不提交；只跑增量 contract/real Git 测试及Ruff/Mypy。
回滚新模块和未消费的入口；已有新计划需保留兼容reader，不能删除审计事实。
