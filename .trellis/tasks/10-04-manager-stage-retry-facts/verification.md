# 增量验证

- Red：`.venv/bin/pytest -q --tb=short tests/manager/test_stage_coordination.py -k automatic_design_retry`，1 failed；缺预算的 Manager 返回 WAITING_HUMAN，真实联合交付服务未推进到 DeliveryReached。
- Green：`.venv/bin/pytest -q --tb=short tests/manager/test_stage_coordination.py tests/manager/test_manager_model_execution.py tests/contracts/test_manager_coordination_schema.py`，23 passed。
- `.venv/bin/ruff format ...` 与 `.venv/bin/ruff check src/ai_software_engineer/manager/stage_coordination.py tests/manager/test_stage_coordination.py` 通过。
- `.venv/bin/mypy src/ai_software_engineer/manager/stage_coordination.py` 通过；`git diff --check` 通过。
- 正向自动重试、600→1200、原 Product 批准不变、三上游角色、work/transient/capacity 耗尽、非 retryable/上下文/非上游拒绝、旧 advice 重读与 stale 校验均覆盖。未运行全量或生产数据库测试，未重放真实模型来造诊断。
- 真实存量需求已通过原生 Continue 使用既有 1200 秒窗口；首次 timeout 和 Manager 暂停记录保留。新代码尚未部署，等待当前 Operation 结束；新诊断输入的效果尚待真实后续调用验证。
- UI 浏览器工具不可用，不宣称浏览器验收。
