# Verification

本次仅运行增量测试，不运行全量测试，不改生产 Task/审批/队列或原工作区。

## 增量结果

```bash
.venv/bin/pytest -q --tb=short tests/manager/test_legacy_local_execution.py \
  tests/manager/test_legacy_containment.py tests/web_console/test_legacy_rescue_acceptance.py \
  tests/contracts/test_local_legacy_rescue_schema.py
```

最终 **144 passed in 4.21s**。覆盖进程归属、内核名字、动作/参数边界、孤儿工具、活动 shell、
macOS/Linux、same-PID exec drift、fresh coverage 缺失、调查拒绝、Console WAITING 和 Schema。
原有 Starlette/httpx 测试兼容性 deprecation warnings 两条，不是本次失败。

```bash
.venv/bin/pytest -q --tb=short tests/manager/test_legacy_rescue_delivery.py \
  -k 'False-False-True or False-True-True' --maxfail=1
```

最终 **2 passed, 3 deselected in 42.04s**。独立测试 MySQL、真实 Git、fake native roles；
真实 scanner 仅替换 OS reads，通过生产公开 Host 的准备、工程确认和同 Task 新 Coder/QA/Review。
绑定到 SQL 消费前的崩溃、随后重放、完整草稿与旧 UNKNOWN 审计保持。没有模型供应商调用。

三份改动 Python 文件：Ruff、format check、strict mypy 均通过，git diff --check 通过。
独立只读复核发现的五个问题已修复；最终复核无阻止提交项，并独立跑过 87 个 scanner 用例，
随后新增的活动/停止 shell 两个边界由最终增量套件覆盖。未改前端 DOM，未跑浏览器或全量测试。

## 存量数据处置

目标 `task_dc5cf0aee44e5ffe0cb600557204e0d0`。在当前维护 Codex 与 ASE 服务保持在线时，对同一个原 Coder checkout 只读比较 `fd05841` scanner 和修复后的 scanner：旧版本 `CODEX_WRAPPER_ACTIVE`，修复版本无 blockers。对完整原工作区文件和 Git index 做前后 SHA 比较均相同。未核准方案或启动下一轮。

本次无需改库：误判来自即时 OS 观察，现有 UNKNOWN、完整现场和操作历史保留。用户在空闲时受控重启服务加载修复，回原需求点击“重新检查恢复前提”/“准备保留进度的恢复方案”；仅确认旧执行及派生工具确已结束后批准精确方案。无需关闭维护会话或重建需求。

回滚：受控停服 → 回滚本提交到 fd05841 → 启动；禁止重写历史或清空草稿。只读即时观察不会生成恢复方案或工程授权。
