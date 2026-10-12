# 最小原因保真设计

## 因果与边界

`bounded_verification_command` 的真实收尾调用 `finish_owned_process`；后者的
`OwnedProcessesUncertain(RuntimeError)` 代表 owned capture/stop/output 最终确认失败。
discovery 的 image/daemon 边界原来将它归入通用 RuntimeError，误报镜像或 daemon 不可用。
context 边界没有同等 typed 保护。短命真实 fixture 只在 image 首次 capture 注入未知，完整
复现了错误分类；没有复现生产 PID 802 最初 capture 的具体 OS 故障。

## 选择

1. 在唯一领域 enum 中新增 `PROCESS_STATE_UNCONFIRMED`，wire 固定为
   `VERIFICATION_PROCESS_STATE_UNCONFIRMED`；不新增自由文本诊断、权限或恢复计划。
2. `_read_command` 明确捕获 `OwnedProcessesUncertain` 并抛不带原错误消息的
   `PythonMysqlDiscoveryError`。不捕获通用 RuntimeError 来假定缺 stop proof。
3. context/daemon/image 先 rethrow typed discovery error，再保留已有 stage-specific 分类。
4. 原 native verifier 与 production preflight 无需改实现：它们已经保留 error.code。同步
   唯一嵌入此 enum 的发布 Schema，并测试 model 完整 parity 和 typed receipt/hash。
5. delivery-wait 复用现有中文 detail mapping。新原因单独说明平台负责核验原探测/收尾；
   复查前提是补齐实际结束事实。拉取镜像、重复检查或当前 PID 缺席都无法重建丢失证明。

## 未改变的合同

真实 registry 仍保留 unknown，`require_stopped`/`await_stopped` 仍拒绝。后续两次合法
probe 可各自 READY，但不清除旧 unknown。不修改 owned/session/service lifecycle，不访问
生产，不改 Task/Queue/Operation/approval/verdict/历史 bytes，不审批或继续 K1。

存量故障实例不能被新代码追补原 proof；Root 的独立受控服务诊断/维护负责部署边界。
测试、风险与回滚见 `verification.md`，实现范围见 `task.json`。
