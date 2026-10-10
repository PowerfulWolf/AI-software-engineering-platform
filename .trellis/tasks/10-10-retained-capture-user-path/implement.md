# 实施记录

已复现实际 `reconcile_capture` 在 `MutationTextBody` 的敏感检测拒绝，无 receipt 写入。
并行检查源码扫描、已停止事实展示和前端 HANDLE 的操作路径。

## 等待诊断与用户入口实施

- 真实 v2 Git fixture 先复现：原 `capture-start`/`capture-stop` 合法、原进程组已停止、
  敏感正文使完整 mutation capture 拒绝；旧 HANDLE 丢失已核验停止事实并缺少具体安全原因。
- `validate_capture_stop` 为 reconcile 与只读 `DeliveryWaitFactCollector.observe_stop` 共用：
  exact request/Task intent/revision/policy、原 start/stop 摘要和时间、完整 scope、历史生产者
  及不可变 claim 字段、任务锁和当前进程组共同校验。Lease heartbeat 只允许 `expires_at`
  合法续期，assignment/model/lease 其他字段、worker 和原 claim 时间不能漂移。
- Host 在 queue idle fence 中连接 read observer。INSPECT 只读 stop，不封存 receipt；HANDLE
  捕获拒绝只保存有限 `WORKSPACE_CAPTURE_REJECTED` 诊断、stop digest 和真实 cause，保持
  outcome/checkpoint 缺项、无 resolution，原源码/停止记录/Task/事件/额度不改写。
- 原进程组仍在运行或当前 queue claim 未释放，显示执行等待，不伪称记录损坏。
- 可选 `collection_failure` 为 None 时从 wire/model dump/record identity 省略，旧 digest/key
  重开测试通过；存在时参与新身份。Standalone 与 Console 嵌套 Schema 同步，未知 code、
  缺 stop、伪称未失败或缺 checkpoint 缺项均拒绝；历史 projection 保留安全诊断。
- 当前等待卡片、完整检查、复制报告都区分“已核验停止”和“完整进度尚未封存”。
  PLATFORM_ATTENTION 显式提供“平台修复后重新处理”，使用 exact HANDLE。
  原继续审批、范围、独立 QA/Review 不变。操作 capability、控制连接或事实失效时旧按钮
  callback 拒提交；不可用时不在用户操作/复制报告中承诺隐藏按钮。

## 增量验证

Red 已实际运行：

```text
pytest tests/manager/test_wait_fact_collection.py::test_rejected_full_source_capture_preserves_verified_stop_and_explains_the_real_wait
FAILED: collection_failure absent
node --test --test-name-pattern='platform repair retry handles' tests/team_view/engineering-wait.test.cjs
FAILED: verified stop/retry action absent
```

Green：

```text
.venv/bin/pytest -q tests/manager/test_wait_fact_collection.py tests/manager/test_delivery_wait.py tests/domain/test_delivery_resolution_schema.py tests/team_view/test_engineering_history.py tests/orchestration/test_capture_reconciliation.py
131 passed (89.82 s)
```

随后补充 queue/process 不确定分类与 heartbeat 正向边界，最新相关 3 个 selector 为 9 passed；
`node --test tests/team_view/engineering-wait.test.cjs` 为 46 passed。
本次 6 个生产源文件 strict Mypy 与所有本分工 Python 文件 Ruff 通过；`git diff --check` 通过。
未跑全量测试，也未修改真实运行记录、操纵服务或推进生产需求。

## 存量与回滚说明

原 K1 的启动/停止、失败 Handling、Task 与草稿保留，无数据库迁移。
修复服务加载后通过原需求 exact HANDLE 再处理；完整封存和冻结工程额度通过才产生新继续事实。
不把旧失败改成成功、不凭停止单独批准、不重建需求。真实生产恢复验证由主任务继续。

可选字段提供新代码读取旧记录的兼容。旧二进制对新字段仍严格拒绝；已有新诊断后回滚行为
必须保留 domain/schema/history 的新字段读取支持，不能删除或改写审计记录来让旧版读取成功。
