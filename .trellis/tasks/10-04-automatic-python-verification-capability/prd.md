# Python 候选自动生成受控增量验证能力

## 问题

QA/Reviewer 为安全原因没有原生 shell、文件和 Git 工具。没有受控验证 capability 时，模型只能
返回 `VERIFICATION_COMMAND_TOOL_UNAVAILABLE`，即使候选已有明确的增量测试映射也会必然阻塞。
此前 `DeliveryResumeController` 的默认验证计划只按 Swift capability 探测，Python 项目必须由人
手工重复提交全部 `--python-test` 选择。

## 目标与边界

在生成新的候选验证计划时，从已校验的 Plan 与 implementation artifact 中读取精确
`tests/**/test_*.py::node` 选择并按 criterion 合并，只有覆盖全部验收标准且不超过 32 个节点时才
生成 Python/MySQL capability。发现不完整映射就保留人工入口，不猜测测试范围。新计划仍需要用户
对 exact SHA 审批；历史计划和平台持久化交付事实不迁移。

## 验收标准

- Python 候选的 Plan test strategy 中的精确节点能生成稳定、criterion 完整覆盖的 `PytestSelection`。
- symbolic test ID、文件级路径、marker 和缺失 criterion 不生成 capability。
- Swift capability 仍只由候选 revision 的 regular 顶层 `Package.swift` 选择。
- 仅运行恢复/验证相关增量测试；不运行全量测试。
