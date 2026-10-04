# 增量验证记录

```text
./.venv/bin/pytest -q tests/recovery/test_latest_verification_plan.py \
  tests/recovery/test_verification_reviewer_resume.py \
  tests/recovery/test_verification_context_budget.py --tb=short
13 passed in 4.51s

./.venv/bin/ruff check src/ai_software_engineer/recovery/verification_entry.py \
  tests/recovery/test_latest_verification_plan.py
passed

./.venv/bin/ruff format --check src/ai_software_engineer/recovery/verification_entry.py \
  tests/recovery/test_latest_verification_plan.py
passed

git diff --check
passed
```

未运行全量测试，未修改存量 sidecar/MySQL/Task/审批/候选事实。
