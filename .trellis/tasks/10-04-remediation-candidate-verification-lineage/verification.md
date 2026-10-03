# 增量验证记录

## 结果

修复统一了首次候选与 QA FAIL / Review REJECT 后 remediation Implementation 的封存链校验。
remediation 必须以原 Plan 为首个父项、引用上一版 Implementation、携带同一旧 candidate 的
有效反馈，并继续执行同一 candidate SHA、独立角色和完整 artifact lineage 检查。存量 Task、
StateEvent、Artifact、verdict、审批和目标仓库没有被修改。

```text
.venv/bin/pytest -q tests/agents/test_candidate_source_binding.py tests/recovery/test_candidate_verification.py tests/recovery/test_verification_routing.py --tb=short
34 passed in 2.79s

.venv/bin/ruff check <4 changed Python files>
All checks passed

.venv/bin/ruff format --check <4 changed Python files>
4 files already formatted

git diff --check
passed
```

未运行全量测试。当前 K1 独立验证计划的第一次 QA 运行仍保留失败事实：Codex 输出引用了
不存在的 evidence（`UNKNOWN_EVIDENCE_REFERENCE`），平台安全停止，没有伪造 QA verdict。
部署本修复后必须新建、精确审批并运行新的验证计划，不能重放旧运行。

## 存量数据处置与回滚

无需迁移或直接改库。旧 QA FAIL、Coder remediation、审批和验证失败记录保持不可变；新版本
仅改变未来读取与验证路径。若部署后发现问题，回退本次平台提交并重启 ASE，保留已有 sidecar
事实，再按恢复入口生成新的精确计划。
