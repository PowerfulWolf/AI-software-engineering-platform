# Implementation log

## Initial diagnosis

- `ase request status <delivery>` 在无默认 Project 的多 Project 配置下未传 Delivery ID，直接报“select a Project”。
- `_facts_for_checkpoint` 将 preparation digest 漂移抛为裸 `ValueError`，`_guard` 只保留异常类型，CLI/页面无法理解原因。
- Team View 对候选上下文预算、认证、限流、超时和非法 evidence 等稳定事实统一显示“执行失败”。

历史 durable facts 仅用于验证和展示，不直接修复；真实 K1 继续交付需以当前 preparation 创建新的精确 recovery/verification lineage。
