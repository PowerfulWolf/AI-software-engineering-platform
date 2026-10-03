# 增量验证记录

本修复在 `ProductionTeamReader` 的一次 snapshot 生命周期内缓存模型路由记录和候选分支查找。
缓存只存在于当前调用，不改变 sidecar、MySQL 或状态事实；每个新的 snapshot 仍重新读取、校验
symlink、文件、Schema、SHA 和 Git 事实。

```text
.venv/bin/pytest -q tests/team_view/test_run_attempt_cache.py tests/team_view/test_execution_history.py tests/team_view/test_dispatch_identity.py --tb=short
7 passed

.venv/bin/ruff check src/ai_software_engineer/team_view/reader.py tests/team_view/test_run_attempt_cache.py
passed

.venv/bin/ruff format --check src/ai_software_engineer/team_view/reader.py tests/team_view/test_run_attempt_cache.py
passed

git diff --check
passed
```

在当前 K1 sidecar 上使用同一只读 Team snapshot 入口测得单次读取约由 8.3 秒降至 4.0 秒；完整
历史仍返回 44 个 Task 和全部验证记录。未运行全量测试。

## 存量数据处置与回滚

无需迁移或直接修改存量 sidecar、MySQL、Task、StateEvent、Artifact、Operation 或 verdict。
回退本次平台提交并重启 `ase-console` 即可；所有原始路由记录和 Delivery checkpoint 保留。
