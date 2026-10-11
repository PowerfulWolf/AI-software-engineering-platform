# 实现与交付

## 变更

生产代码仅三行：在 `work_queue/baseline.py` 导入已有 `source_inspection_scope`，为
`consumptions` 加装饰器及说明。连接/SELECT/逐行完整 `_decode`/序列排序原样保留。
新增真实 Plan/Binding 解码回归，只替代 SQL port；没有新缓存、依赖或 Schema 改动。

## 测量与回归

变更前运行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q \
  tests/work_queue/test_baseline_consumption_read_scope.py::test_full_consumption_read_scans_once_and_next_read_rechecks_exact_bytes
```

预期检查一次，实际解析完整源码 20 次，`1 failed in 10.72s`。

精确只读封存生产 Plan 的隔离测量：

| 读取 | 变更前 | 变更后 |
| --- | --- | --- |
| 同一个完整 `BaselineQueueConsumption.model_validate` 输入 | 6.812s | 0.319s / 0.316s |
| 实际完整 JSON 行 `_decode`，独立 SQL port | 8.884s | `consumptions` 0.448s / 0.446s |

后者完整输出 wire/SHA 均相等，查询计数为 1 然后 2；没有 SQL/model 访问或保存/打印正文。
已有3 bindings 的 store 读取约1.6s，当前 joint journal 顶层60 checkpoint cold0.631s /
warm0.042s。微基准识别了消费多层完整源码重复扫描，并不宣称公开 Operation 整体缩短20倍，
也不把临时解析之后的物理内存高水位判断为已证实的泄漏。

增量验证命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q \
  tests/work_queue/test_baseline_consumption_read_scope.py \
  tests/work_queue/test_baseline_history.py \
  tests/manager/test_baseline_source_inspection_scope.py \
  tests/context/test_source_inspection_scope.py \
  tests/context/test_generic_redaction_scope.py
python -m ruff check src/ai_software_engineer/work_queue/baseline.py \
  tests/work_queue/test_baseline_consumption_read_scope.py
python -m ruff format --check src/ai_software_engineer/work_queue/baseline.py \
  tests/work_queue/test_baseline_consumption_read_scope.py
MYPYPATH=src python -m mypy --follow-imports=silent \
  src/ai_software_engineer/work_queue/baseline.py \
  tests/work_queue/test_baseline_consumption_read_scope.py
git diff --check
```

增量 pytest **68 passed in 269.60s**；Ruff/format、strict Mypy 两个文件与 diff check
全部通过。只跑上述五个相关文件，没有全量测试、真实 SQL 或模型调用。

## 独立审查

独立只读 reviewer `/root/recovery_read_cost/task_projection_reuse` 相对精确
`bd06ce6ce67642aeee0d8f426ded6c6f31373155` 完成 Standards/Spec 两轴审查，均无阻断。
确认原 SQL/完整 Plan/身份/SHA 保留，现有 bounded scope 只缓存 exact text/path 的纯检测
事实且 finally reset；测试走真实 `_decode` 并覆盖 fresh query/wire/SHA、secret/path/tamper、
成功/校验/查询异常清理和 typed capture weakref。

## 存量数据处置与回滚

无需修改 SQL、Requirement/Task/Operation/Plan/Binding/审批或工作区。保留原需求和所有
完整历史，待当前真实角色安全结束且服务闲置时再由 Root 通过受控流程加载修复；
本任务不操作生产、主 checkout、服务或模型。当前执行不得为这次性能优化而中断。

回滚仅撤销装饰器/导入，恢复重复检查耗时；已有 durable facts 完全兼容。

## 根因与预防

之前已优化 scoped store 读取，但实际队列消费会重新深校验每个完整 Plan，两层入口没有
同一纯检查生命周期。仅验证单个 store 的检查次数无法覆盖 `consumptions → _decode`
这一真实下游路径。预防方式是对完整持久化行的真实消费者计数重复纯工作，且同时检查
独立下一次读取的 freshness、篡改拒绝和作用域退出，不引入跨请求事实/权限缓存。
