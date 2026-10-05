# 设计

继续使用 `localize_blocking_text(value: str | None) -> str | None` 与
`humanizeBlockingText(value) -> string` 的既有精确字面映射，补充 producer 已存在的 14 条固定
阶段提示。没有新增一般接口、领域 payload 或动态解析能力。

`productExecutionSummary` 的 reason、next_action，`requestBlockerSection` 的建议操作，以及
`requestOperationHistory` 的旧操作下一步通过既有 renderer 展示中文；源对象保持不变。
只读 native engineering next_action 若匹配同一固定集合亦使用相同展示函数。

Python 参数化测试覆盖有限集合与用户引用保留；实际运行 JavaScript renderer 验证两端契约
一致。轻量 DOM 与真实浏览器分别验证遗漏展示路径、待审批控件及原始事实未被改变。
