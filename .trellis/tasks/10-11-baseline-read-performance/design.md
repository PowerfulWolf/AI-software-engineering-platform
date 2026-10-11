# 设计契约

`FileExecutionBaselineStore._required_patch(binding: ExecutionBaselineBinding, plan: ExecutionBaselinePlan) -> str` 是内部 typed seam。调用者须在本调用内完成 binding 与 plan 校验；helper 额外要求 `binding.plan_sha256 == plan.plan_sha256`，并保留完整 patch URI、UTF-8 SHA/bytes、Task ID、input mode 和 purpose 检查。

`bindings_for_task` 保留完整 list、前驱、`plan()`、`start()`、plan/start 相等、事实和 `_require_authorized_binding` 顺序，只把最终 `required_context(item)` 改为 `_required_patch(item, plan)`。不改 `put_binding` 的公开 Context 重读路径，也不缓存授权。

`required_context` 仍首先 `binding.validate_integrity()` 与 `self.plan(binding.plan_sha256)`，调用私有 helper 后按原表达式生成全文。全文没有静默截断或语义变化。

Good：一个真实 binding 一次 plan get，全部原权威检查保留。Base：独立 Context 调用每次重新读 plan。Bad：错 plan ID、补丁引用/hash/字节数或 Task/模式/用途，均 ValueError；不存在的原 plan、start/authority、错误前驱/epoch 按原有边界拒绝。

验证：真实 store `_read_name` namespace 计数、保留正文逐字相等、下一次读取篡改反例、现有完整 baseline/paused/native-rule/read-side 契约回归。性能数字以另行串行只读测量为准，不扩大缓存到请求外。
