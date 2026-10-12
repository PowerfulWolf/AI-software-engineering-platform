# 存储作用域设计

不变接口 `DeliveryWaitService._resolve(command, automatic=True)`。唯一路径变化：
`state/delivery-wait-authority-<digest(task.id)>`，digest 使用既有 canonical SHA 函数。
root 是现有 sidecar state 的单个子目录，保持 FileRecoveryStore.initialize 的安全原子创建。
RecoveryScope 仍绑定 Team/Repository/root 与 delivery_wait_<task.id>，Agent 不能选路径。

旧 resolution/handling 重放仍读取原 immutable decision，queue 消费其嵌入 exact admission。
若 shared Team ledger 已写、本地或 decision 发布中断，EngineeringAuthority.admit 原 Task
与 exact plan/facts/capabilities重新验证，返回原 admission，再复制到新的本地 scoped root。
canonical budget 不从local目录计数，因而不产生第二次授权或预算退款。

没有 Schema/API/state/verdict 变化。旧固定目录保持不读不写；它不是新 Task 授权来源。
当前新目录错scope、非普通/unsafe path和坏记录继续fail closed。

Good: 新Task遇到同仓库旧Task本地scope，按自己的冻结policy与共享预算处理。
Base: 同Task完整decisions原样重放。Bad: overwrite旧scope/改Task身份/重置budget或
用无关local目录判断已授权。
