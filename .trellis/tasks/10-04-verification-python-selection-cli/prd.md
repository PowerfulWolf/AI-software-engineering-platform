# 让候选验证 CLI 能提交精确 Python 增量选择

## 问题

`CandidateVerificationEntry` 已支持 `python_mysql_tests`，但 `ase verify-propose` 没有暴露该
输入。Python 候选因此只能创建没有受控执行回执的计划；Codex CLI fallback 又禁止原生执行工具，
QA 只能安全地产出 `VERIFIER_TOOL_UNAVAILABLE`，需求无法继续。

## 目标

- 通过 CLI 重复传入精确 pytest 节点及验收标准 ID；
- 在计划中封存受控 Python/MySQL 执行能力，保留候选、Task、审批和独立角色边界；
- 错误输入在模型调用和 Host 构造前 fail closed，错误提示中文；
- 保留不带选择参数的旧 CLI 兼容行为。

## 验收标准

- 合法的 `node=criterion[,criterion]` 被解析为 typed `PytestSelection` 并传到 Entry；
- 缺失 `=` 或 criterion 时返回非零且不构造 TeamHost；
- 仅运行 CLI、恢复和验证相关增量测试。
