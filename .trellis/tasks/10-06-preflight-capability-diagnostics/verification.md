# 验证记录

## 变更结论

受控 Python/MySQL 宿主发现不再把所有失败压缩成同一个不可定位的原因。系统现在封存有限的
安全分类，并在工程等待调查结果中生成去重后的中文处理提示。分类不包含原始 stderr、完整命令、
绝对路径、DSN、密码或环境变量。

旧的 preflight receipt 没有被回写，也不会根据历史泛化记录猜测根因。用户需要在服务更新后对
同一个需求重新点击“调查工程等待”，才能获得当前宿主的实际分类。新诊断不会自动启动 Docker、
安装依赖、修改 Task、队列、审批或解除等待。

## 增量验证

- `pytest -q --tb=short tests/manager/test_python_verification_discovery.py tests/manager/test_delivery_preflight.py tests/manager/test_delivery_wait.py tests/manager/test_native_verification.py` — 131 passed
- `pytest -q --tb=short tests/manager/test_delivery_wait.py -k 'preflight_detail_action or preflight or investigation'` — 4 passed
- `pytest -q --tb=short tests/manager/test_python_verification_discovery.py -k 'host_discovery_classifies_each_safe_boundary or unsupported_platform'` — 12 passed
- `node --test tests/team_view/engineering-wait.test.cjs` — 10 passed
- `ruff check`（全部改动的生产代码和测试文件）— passed
- `mypy`（6 个改动的生产文件，strict）— passed
- JSON Schema/Schema parity 增量回归 — 118 passed（此前已完成）
- `git diff --check` — passed

没有运行全量测试，也没有执行真实的调查、审批、恢复、继续交付或 Task/队列修改。

## 存量数据与回滚

旧 FAILED Operation、旧 preflight receipt、Task 和等待事实保持不变。回滚时只需回退本次服务
代码提交并重启服务；不删除 immutable receipt，不直接改库，也不替用户解除等待。回滚后旧 receipt
仍可读取，但新分类和中文处理提示不再产生。
