# 实现

修正 `_read_git_info` 对 `packed-refs` 的字段顺序解析，并增加
`test_git_packed_refs_preserve_revision_for_native_rule_recovery`。只执行 RepositoryProfile
增量测试和恢复相关回归；不改动目标仓库或 ASE sidecar 中的持久化事实。
