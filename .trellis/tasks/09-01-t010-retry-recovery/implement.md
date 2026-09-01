# T010 Implementation Plan

1. 为 StateEvent 增加审计 `attempt`，扩展状态机的 planning/implementation BLOCKED 边。
2. 为 SQLite TaskRepository 增加幂等、单调的 `record_attempt` checkpoint。
3. 为 ArtifactStore 增加 `list_for_task`，用于重启时重新校验并恢复 lineage。
4. 实现 `RetryingOrchestrator`，复用 T009 的 Context、Agent、Artifact 和 state guards。
5. 增加 transient timeout、QA finding、budget exhausted、T009 checkpoint recovery 测试。
6. 同步 docs/spec，并运行完整 pytest、ruff、mypy、build、lock 和 diff 检查。

## 验证命令

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
git diff --check
```
