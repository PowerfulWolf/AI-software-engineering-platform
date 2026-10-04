# 设计

1. 共享 `knowledge_phase_timeout`，Delivery 每次咨询使用角色已接纳 timeout 且上限 600 秒；上游继续原 stage 窗口。typed local timeout 不扣瞬态额度，稳定原因由 Manager 映射为执行容量停止。
2. 原 Task 保留。consistent read-only snapshot 验证精确三事件、首次 attempt、同一计划、原 allocation、CLOSED 队列、released claim、无 accepted 产物或真实代码调用。
3. 复用 append-only pre-execution plan/authorization 和 fenced continuation，增加知识超时 kind。计划显式区分 source 与 target base，旧缺省字段 digest 兼容；新 kind 的 Schema/类型都要求 source。
4. 使用 current target backend 提案，批准后先 attach successor，再用同一 catalog 的 current backend 原生继续；下次 Host 从 successor durable preparation 重建 frozen backend。禁止改旧 frozen source。
5. 中英文只读显示分别映射，知识调用与代码未启动事实明确。业务范围、预算、权限和独立 QA/Reviewer 不改变。

允许路径：本任务修改列出的 knowledge、orchestration/retry、manager/delivery、recovery、Console/Team 显示、相关增量 tests、Schema generator、docs 和 Trellis 契约。回滚点为 baa5531，消费新计划后需兼容读取器。
