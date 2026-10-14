# Design

共享 host-owned ServicePauseControl 在 Console Operation 的 ContextVar scope 激活。begin_shutdown
在关闭 admission 的同一 lifecycle 锁内请求暂停。新模型/队列领取前检查；保存、心跳与最终
owner fence 不受 pause flag 的通用异常破坏。当前本机 runner 在原 SID/birth 归属下观察窗口，
超过窗口复用 OwnedSessionController.stop，保存 kind=service_pause 的真实停止证明后返回。

SERVICE_PAUSED 是非 transient AgentErrorCode；完整 invocation/route/knowledge 结果先封存，
Orchestrator/Supervisor 将其转为 recoverable wait，保留原 Task checkpoint 并释放 Lease。
边界暂停只留下已生成且尚未领取的下一 WorkItem，不制造新的调用。同步 HTTP 允许真实当前
round trip 返回；后续模型回合、工具和 route 被暂停边界拒绝。

Coder service_pause capture 是只读原执行证据，不能自动扩大旧 allowed_causes。合法完整
v2 capture 进入精确 SOURCE_REBIND 工程计划，使用 ordinary 工作预留且需要原有明确授权；
新审批不会修改旧 Task/权限或旧 ProductSpec。旧无能力 Task 保留现场并走原救援流程。

服务替换仍要求 WriteGate + Operation final save + dispatcher/index stop + owned session/EOF
和 durable finalization 全部成立。未证明会话停止/封存失败继续 REFUSED，绝不清空 registry 或强杀 Host。
部署边界：正在运行的旧进程不会因磁盘更新获得新能力；升级必须使用既有安全停止并核验原执行。

## 已完成维护轮次的再次退役

实机部署发现旧 Host 普通 stop=REFUSED/OWNED_PROCESSES/UNCONFIRMED，且已存在已完成并正常接纳的
维护轮次。修复限定在可信本机维护服务，不给 Agent 新能力。新 FaultRetirementPlan 精确绑定上一轮
marker/completed/admitted 字节及全部 completion plans/receipts 的清单和 SHA。prepare 只归档控制文件
副本，不改变运行模式。execute 在任何信号/控制文件变更前，用原 marker 的 exact compare + atomic
replace 发布 typed pending epoch；所有启动门禁在 pending 时拒绝构造 writer。随后在 replacement lock
内把已核验的上一轮 completion 目录移入该新退役的 previous-maintenance 归档，移除已有归档精确副本
对应的固定 completed/admitted 文件。发生中断只能同 plan 从精确的 root/archive 阶段继续。

真实退役封存后，先把新 marker 存为 immutable archive record，再从 exact pending marker 原子切到
新 inspection marker。保留前轮完整退休/完成/接纳链；读取新 marker 时递归验证前轮控制链。
新轮必须重新执行独立 maintenance completion/normal admission，前轮批准不能复用。
直接 Host normal 构造也持有同一 replacement lock，防止旧 normal admission 与切换竞争。

不改数据库或未知旧 execution；新 marker 不把旧 REFUSED/UNKNOWN 变成 READY。回滚不可覆盖已封存
维护记录；pending 只能使用同 SHA 的当前维护执行器修复，不启动普通服务。
