# Implementation log

## Initial diagnosis

- `ase request status <delivery>` 在无默认 Project 的多 Project 配置下未传 Delivery ID，直接报“select a Project”。
- `_facts_for_checkpoint` 将 preparation digest 漂移抛为裸 `ValueError`，`_guard` 只保留异常类型，CLI/页面无法理解原因。
- Team View 对候选上下文预算、认证、限流、超时和非法 evidence 等稳定事实统一显示“执行失败”。

历史 durable facts 仅用于验证和展示，不直接修复；真实 K1 继续交付需以当前 preparation 创建新的精确 recovery/verification lineage。

## QA 增量测试约束

候选复核期间发现 Codex QA 忽略了已有的“默认只跑聚焦测试”提示，启动了无选择器的
`pytest -m not mysql` 全仓测试，违反了操作者把全量回归留给人工执行的约束。QA prompt
现明确要求每次 pytest 都带 `tests/` 下的文件或节点选择器；缺少验收映射时返回
`INCREMENTAL_TEST_SELECTION_REQUIRED`，不得自行扩大到全仓。该修复只改变后续 Agent 的
可执行指引，不修改已经封存的 run、artifact 或 verdict。
