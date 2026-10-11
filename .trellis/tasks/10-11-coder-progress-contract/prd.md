# 精确开发检查点输出契约

## Goal
本轮 request.attempt=4 的模型返回 checkpoint_sequence=9，被编排正确拒绝。
在当前调用输出边界明确约束其精确序号，避免先封存成功再误报平台不变量失败。

## Acceptance
- Codex/Responses动态Schema及共享prompt使用request.attempt的精确值。
- live adapter在封存SUCCEEDED前拒绝错误序号，不自动改写模型内容。
- 原有编排gate保持；旧封存结果原字节/摘要可读但不可被重新接纳。
- 先红回归、只增量测试；不改审批、预算、权限或生产库。

## Existing data
不修改旧attempt4结果；其续跑需独立受控现场/决定契约，不以本修复补造合法产物。

## Rollback
消费新结果前可回滚代码；保持历史读取兼容，不删除任何运行/结果。
