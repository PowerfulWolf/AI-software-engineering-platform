# 实现与存量处置

共享节点派生接纳同 Project 交付 INTERRUPTED 终态，显示红色操作已中断；在预算、当前
等待/过期、有效 claim、精确审批和 successor gates 之后读取，旧失败不遮新工作。
新增严格 canResumeUpstreamStage，正常继续设计/计划直接可见并提交现有 CONTINUE typed
intent、绑定当前 checkpoint。首轮 PRODUCT_APPROVAL 已保存批准后的 FAILED 复用原 retry
gate，不重复 Product 批准。

UNKNOWN 工作无证据显示等待工程处理；TaskGroup、TaskPresentation、摘要、assignment、
成员队列与 sidebar 一致，普通 Continue 拒绝。真实角色 claim/排队/重试覆盖产品原因、责任
和下一步。NEW/PLANNING 仅在匹配运行中的交付 Operation、无真实 blocker/wait/expired 时
显示灰色准备执行。原 UNKNOWN 保持工程可读，不宣称模型在线或进程停止。

成员当前岗位身份不改，进行中只收真实运行；paused 使用具体状态。工作行优先展示本成员
assignmentBadge，完整 assignment 入缓存签名，连续 RUNNING 角色切换不会保留旧蓝 badge。
历史上游岗位保留已完成语义，native 历史失败保留，Team 待处理计数采用 requestGroup。

固定 Host 停止英文精确映射覆盖当前原因、通知和 Operation 历史。中断/停止 badge 使用
局部红色 CSS，不变更全局 warn。UI 旧 fixture 改为真实角色 claim；stage-only UNKNOWN/
legacy verifier 更新为工程等待，历史 Task 补真实 source delivery 归属与先前活动时间。

存量无需改库或改 sealed journal/Task/审批/预算。root 只读确认旧 Host 与精确 baseline CWD
无 owned Codex 后已经公共 CONTINUE 新建 Operation；旧中断 attempt 不退款，批准不重做。
本任务没有操作生产、重启、commit/push/deploy。回滚前端资产并刷新，不改变所有历史事实。

限制：HOST_INTERRUPTED 不是 Codex stop receipt；上游 owned-run/progress/drain 属于独立后续
改造，不在本 UI 补丁声称完成。
