# 设计

`NativeCandidateSourceReader.inspect()` 先读取并验证当前终态候选来源，得到唯一的
`source.inputs.candidate_revision`。扫描历史计划时先由 scoped recovery store 解析每个
`verification-plan-<sha>.json`，保留其既有的路径、Schema、摘要、scope 和关联记录检查；只有
typed plan 的候选 SHA 与当前来源精确相等时，才调用 `NativeVerificationFacts.validate()`。

这不是跨 snapshot 缓存：每次 `latest_project()` 都重新读取目录、重新校验计划和当前来源。匹配
计划的完整验证仍保持原有 fail-closed 逻辑；不匹配计划被安全忽略，因为它属于旧候选的历史事实。
