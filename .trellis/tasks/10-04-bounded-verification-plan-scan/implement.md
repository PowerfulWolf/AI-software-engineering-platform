# 实现

`CandidateVerificationEntry.latest_project()` 现在在当前终态来源读取一次候选 SHA，并复用当前
扫描实例的 `NativeVerificationFacts`。每个历史计划仍通过 scoped recovery store 解析和校验；
候选 SHA 不匹配时直接跳过重型 current-fact 校验，匹配时保持原有完整 `validate()` 和最新时间
选择逻辑。

新增回归测试构造旧候选和当前候选两个合法计划，确认旧计划不会调用 Native 验证、当前计划会
被选中。未改变 sidecar 或 MySQL 数据。
