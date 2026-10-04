# 增量验证记录

```text
./.venv/bin/pytest -q tests/recovery/test_delivery_continuation.py \
  tests/recovery/test_latest_verification_plan.py \
  tests/recovery/test_verification_reviewer_resume.py \
  tests/recovery/test_verification_context_budget.py --tb=short
33 passed in 7.22s

./.venv/bin/ruff check src/ai_software_engineer/recovery/resume.py \
  tests/recovery/test_delivery_continuation.py
passed

./.venv/bin/ruff format --check src/ai_software_engineer/recovery/resume.py \
  tests/recovery/test_delivery_continuation.py
passed

git diff --check
passed
```

另一次扩大筛选的 `tests/recovery/test_resume.py -k 'candidate or verification'` 在既有联合交付
fixture 的 Manager 协调输入不兼容处失败（`DirectoryScope` 结构不匹配），随后中断；该失败未由
本改动触发，未作为全量测试运行，已保留日志供后续单独修复。

未运行全量测试，未修改存量 sidecar/MySQL/Task/审批/候选事实。
