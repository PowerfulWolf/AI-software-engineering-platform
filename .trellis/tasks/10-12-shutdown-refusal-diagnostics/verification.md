# 验证与生产边界

## RED

`PYTHONPATH=src <maintenance>/.venv/bin/python -m pytest -q tests/web_console/test_shutdown_refusal_diagnostics.py --tb=short`

真实coordinator+owned shutdown_failed=True，先1 FAILED/1.00s：`真实执行核验拒绝不能在coordinator边界丢失原因`。
当前实现不是通过猜PID802原因修复，而是保留真实组件下一次返回的typed诊断。

## 已执行增量

- diagnosis/service_lifecycle/shutdown/controlled_host/generated Schema：38 PASS/4.35s。
- Console close/shutdown/terminal/claim-save/resume/drain：16 PASS、12 deselected/3.00s。
- 受控脚本实际restart refusal/resume、stale-ready和跨checkout维护：3 PASS、27 deselected/44.91s。
- 6个代码/测试文件strict mypy PASS；Ruff check/format PASS。

独立review发现并修复startup状态/原因两次读取race，以及cancel覆盖较早Console未核验首因。
新增single-snapshot与首因/timeout升级回归已加入，最终diagnostics+host+Schema窄重跑24 PASS/4.44s；独立review正式14 PASS/0.74s，最终PASS无阻断。无数据库/模型调用或生产写操作；未跑全量测试。

## 存量数据处置

生产原K1Task revision2仍实施前ENVIRONMENT_UNAVAILABLE等待，12个合法草稿保留。
PID802第一次300秒后REFUSED，第二次0.086s拒绝。其旧结果只有固定摘要，真实具体失败环节仍未知。
此修复不读取/修改目标进程内存，不取消sticky、不补造stop/READY、不重写历史或审批。
服务需完成独立可信维护处置后才能加载新版本，测试通过不等于已部署或K1交付。

回滚必须保留理解可选refusal的reader，旧extra-forbid版本不能读新记录；保留原字节和所有历史。
