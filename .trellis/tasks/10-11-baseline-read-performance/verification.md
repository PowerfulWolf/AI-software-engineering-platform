# 验证与部署状态

## 红绿证据

真实 Git/service/store fixture 的完整 binding 读取，原实现失败于实际 `baseline-plans` 读取2次，期望1次；不是仅测试 helper。提取私有 seam 后通过，start/authority各1次不变，后续两次公开 Context 分别再次读取 plan，完整 patch 和 sidecar bytes 保持。

## 增量验证

```sh
uv run pytest -q --tb=short tests/manager/test_baseline_read_reuse.py
# before: 1 failed in 11.82s (baseline-plans 2 != 1)
# after: 1 passed in 10.38s
uv run pytest -q --tb=short tests/manager/test_baseline_read_reuse.py \
  tests/manager/test_execution_baseline.py tests/manager/test_baseline_source_inspection_scope.py \
  tests/manager/test_paused_baseline_service.py tests/manager/test_execution_native_rules.py \
  tests/team_view/test_baseline_snapshot.py
# 43 passed in 315.71s
uv run pytest -q --tb=short tests/manager/test_execution_baseline_native_rules.py \
  tests/manager/test_execution_baseline_context.py
# 14 passed in 106.69s
uv run ruff format src/ai_software_engineer/manager/baseline_store.py tests/manager/test_baseline_read_reuse.py
uv run ruff check src/ai_software_engineer/manager/baseline_store.py tests/manager/test_baseline_read_reuse.py
uv run mypy src/ai_software_engineer/manager/baseline_store.py tests/manager/test_baseline_read_reuse.py
# All checks passed; no issues found in 2 source files
git diff --check
```

新增7项回归含实际读取、URI/hash/bytes/Task/input mode拒绝和先读完整binding后修改plan仍由公开Context重新发现。全部57项相关不同测试通过；不把早期单项重复执行另加。未跑全量测试。

独立只读审查由 `recovery_read_cost/task_projection_reuse` 完成，无阻塞项。核对了全部原 binding/plan/start/authority/facts/predecessor/native epoch 与 scope 检查，公开 Context 和 put_binding 保持独立读盘。主 checkout 和 K1 工作区未修改。

## 性能与限制

已证实减少一次完整计划读盘/解析及一次被丢弃的完整 Context 构造。该工作量结果不证明完整 Team 请求稳定低于5秒，完整 Joint 历史校验等成本仍存在。没有跨请求或跨 Task 缓存，没有减少历史或权限核验。

## 存量数据处置、部署与回滚

无 Schema/SQL/历史 bytes/审批或 Task 修改，无需迁移、不新建需求、不更新执行基线。生产 K1 当前有活跃执行，此修复保留在独立分支，待真实执行全部空闲后受控部署。回滚代码只恢复重复读取，不删除事实、不改变进度或批准。
