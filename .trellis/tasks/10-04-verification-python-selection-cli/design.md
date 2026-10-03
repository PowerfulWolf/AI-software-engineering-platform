# 设计

`recovery.cli.verify_propose` 增加可重复的 `--python-test` 选项。每个值按第一个 `=` 分割，
右侧按逗号得到 criterion IDs，再交由 `PytestSelection` 做 schema/type 校验。解析失败走既有
CLI fail-closed 错误出口；未提供时继续传递 `None`。执行器、receipt、审批和候选验证逻辑不变。
