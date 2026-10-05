# 最小设计

`requestNodeExecution(request)` 终态操作 fallback 增加同 Project 的交付 INTERRUPTED，位于
当前 durable wait、active Operation/role claim、预算、精确审批与无阻塞 successor 之后。
中断只证明该 Console Operation 未完成，不改变已批准 Product 或 Requirement 阶段。

通过已有 `CONTINUE_DELIVERY(project_id, delivery_id, expected_checkpoint_sha256)` 继续当前
DESIGNING/PLANNING，而非重放原 PRODUCT_APPROVAL。门禁由 deterministic application
service 再校验精确 checkpoint、source/provider/claim/预算/审批；前端不得扩大批准权限。

成员队列纯读展示使用当前 requestNodeExecution/Presentation。Request 当前阶段归属保持
不变，中断/缺执行证明移到已阻塞，真实排队/准备/接续保持待完成，运行才进入进行中；成员 badge 与 work-row
增量签名包括派生状态，Operation 轮询能更新显示。

新增固定英文精确映射，通过统一 humanizeBlockingText 覆盖当前原因、历史 Operation 与
notification，不替换原始 API 字段或 audit bytes。

已证实角色 claim/READY/重试与 bootstrap 优先覆盖产品摘要原因、责任和下一步，旧 UNKNOWN
原文只进工程详情。普通 Continue 遇 requiresEngineeringCheck 必须拒绝，不因 groupblocked
合成安全继续能力。current assignment 的 badge 与完整 assignment 进入 work-row 增量签名。

HOST_INTERRUPTED 只证明 Host Operation 停止，不证明旧 Codex 停机。生产接续由 root 先只读
确认旧 Host 和精确 baseline CWD 无 owned Codex，再经公共 CONTINUE；本任务不加 runtime
guard，不实现上游 owned-run/progress/drain，不退还未知中断尝试，也不重做产品批准。
