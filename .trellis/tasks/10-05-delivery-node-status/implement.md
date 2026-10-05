# 实现

新增共享只读 `requestNodeExecution()` 和 `requestNodeBadge()`，由流程、card、详情执行摘要
及 Manager 提示消费。原 API execution UNKNOWN 和所有封存记录保持不变，在工程区以
“执行事实状态”展示。产品执行中的提示为“当前节点正在执行，请等待本阶段处理完成。”。

节点按实际事实区分蓝色执行中、绿色已完成、红色阻塞/需确认/待审批、灰色已排队/待重试/
待开始/状态待核对；都有文字，当前 gate 使用 aria-current。DONE 最优先，忽略遗留展示用
failed/wait 标记后七节点全绿；CLOSED 不因关闭显示完成。

流程位置使用 currentRequestTasks，补足 VERIFY_QA/VERIFY_REVIEW，避免候选验证和返工被
旧 native Task 覆盖。当前 native 执行只接受阶段对应 RUNNING + LEASE_VALID；Task QUEUED/
CONTINUE_REQUIRED 保留 claim 的迁移窗口保持灰色。角色失败保留 operationChildBlocker 的
实际时间边界。card 的增量签名包含节点状态，避免相同阶段在排队/执行切换时保留旧 badge。

既有预算耗尽、Design recovery/recheck、当前精确审批和已终态操作失败进入共享节点派生，
不遮住仍合法执行的最后一轮工作预留。未改控制权限、提交 intent、精确审批或后端 gate。

增量旧测试同步真实语义：无 claim 的 QA fixture 不再宣称“测试中”；待最终确认不再标执行；
局部流程阻塞样式从警告棕色更新为红色。完整历史中的旧 Operation 下一步中文仍保留，相关
断言分别检查当前阻塞、Manager 状态与历史内容，不限制恢复轮次或删除审计记录。

独立 review 再复现并修复：card 增量签名补充 deliveryPhase，使连续 RUNNING 的实现→测试→评审
轮询更新阶段；无当前阻塞的非终态 successor 缺 claim 时保持灰色，不回落到旧 FAILED 或协调
建议，包括当前 NEW/PLANNING 工作。无当前 successor 时，最新同 Project 交付 FAILED 显示
红色阻塞；FAILED.result 按 Schema 必须 null，而 expected_checkpoint 是操作输入，阶段
attempt 已追加新 checkpoint 后模型失败时不能用输入旧摘要隐藏真实失败。
补充真实浏览器连续阶段轮询、旧失败/旧 advice + UNKNOWN successor，以及生产形状
FAILED.result=null、inputOld→currentNew 后真实失败的定向回归。
