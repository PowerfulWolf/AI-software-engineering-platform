# 技术设计

恢复服务将 `repository.repository_root` 传给 `GitWorktreeManager`。Manager 新增只读的 `branch_exists` seam：先验证 Git 根，再把 `show-ref` 返回码 1 解释为缺少 ref，其他返回码转换为稳定 Git 错误。

`read_pre_execution_snapshot` 只接受完整且自洽的首个 Coder 启动前事实：唯一 queue item/step、匹配 admission、无 accepted role artifact、无活动 claim、无模型 route、无保留 worktree，并保留过期 claim 事件作为审计。`read_approved_stages` 始终接收当前 allocation，按其 successor preparation digest 做精确比较。

Good/Base/Bad fixtures 分别覆盖已占用分支、空闲分支/真实 Git 根和 sidecar/活动 claim/额外 role 证据。测试不调用生产模型，也不触碰生产数据库。
