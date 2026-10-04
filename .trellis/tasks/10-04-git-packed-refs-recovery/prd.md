# 修复 packed-refs 恢复阻塞

## 问题

生产目标仓库的 `main` ref 已被 Git 压入 `packed-refs`。RepositoryProfile 读取时把 Git
标准的 `<object-id> <ref>` 行反解析，保存了 `ref` 却把 revision 留为 `unknown`。恢复流程
需要 sealed revision 重新绑定 native rule，因此需求在候选验证失败后无法生成恢复计划。

## 目标与边界

按 Git 原生格式解析 packed refs，保留提交 SHA；新增只读回归测试和 Trellis 记录。不得通过
直接改 MySQL/sidecar 或放宽 native rule 安全校验恢复旧需求。

## 验收标准

- packed-refs 分支能得到正确的 `vcs.revision` 和 `source_revision`。
- 现有 loose ref、无 Git 项目和 revision mismatch 检查保持不变。
- 恢复流程可在 current preparation 上重新生成精确计划；历史候选和失败报告保持可读。
