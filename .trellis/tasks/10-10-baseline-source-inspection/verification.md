# 增量验证与测量

## 红→绿证据

真实完整 Python 源码 fixture 包含 300 个函数及合法属性引用。仅通过公开 service/store
调用观察 stdlib AST 的性能工作量；每个调用的模型与原文件 bytes 完整保留。

| 真实接口 | 修复前相同完整 body 的 parse 次数 | 修复后 |
| --- | ---: | ---: |
| standalone plan | 20 | 1 |
| propose | 55 | 1 |
| execute | 46 | 1 |
| continue | 22 | 1 |
| standalone operation start | 20 | 1 |
| v2 receipt get | 8 | 1 |

各性能回归先在未包装对应接口时失败，再逐项实现。独立第二次调用重新扫描，
caller 在 service 返回后也重新扫描；成功及异常后 ContextVar cache 均为空。
同一 outer scope 下真实文件被改 body/path/摘要依然拒绝，不缓存文件或批准结果。

## 初始诊断（只读，修复前）

- proposal RUNNING→SUCCEEDED：264.508885 秒；PAUSE：243.869420 秒。
- 一次 cProfile，同一进程 sealed plan + receipt：无 scope 4.282050 秒 / 128 AST parse，
  已有 scope 0.206265 秒 / 4 AST parse；两次完整 immutable fingerprints 一致。
- `_inspect_source` 1322→70，`_inspect_patch` 10→1；两次均保留 18 model_validate、
  10 CapturedMutations.validate_capture、2 ExecutionBaselinePlan.validate_plan。
- 该 profile 是不可变记录重读，不能把 proposal/PAUSE 全部分钟数归因于 AST，
  也不能由累计 ru_maxrss 增加宣称泄漏。真实构造仍包含独立 Git、文件观察和 I/O。

## 修复后唯一一次授权实机只读复测

使用正式 read-only baseline store 和 continuation store，在一个有界 scope 内仅重读一组
封存 plan/receipt。不构造 Host、不写目录/锁、不访问 SQL/claim，不调用生产 Git/模型，
未重启、未审批、未 profile。

- wall：0.140249083 秒；AST parse：4；27 个完整 mutation paths，342336 patch bytes。
- plan digest：`9843e812a44fc7cb1f0ebb78449a19c768deec3f5926d620887278af89ad9702`
- receipt digest：`ac5c8b1442eb052f905cde4adb13f13b5a73f72668b659ccb8934187eec8f32b`
- plan 原文件 SHA：`77265163aef33aafee768536d19a49e9a8ac38465808463192e5fab5423a0bbb`
- receipt 原文件 SHA：`0ded9e09ce50c30f9aa1a3c770bf3355aa5d82f52ab462f145927a47cd353197`
- 两文件 SHA 前后不变；退出 scope cache 为 None。

在线负载下的孤立读取不是已部署 HTTP 或完整基线操作的延迟保证。不与带 profiler
的修复前结果直接相除来宣称完整流程加速比。

## 质量门

- Changed-file Ruff：通过。
- Strict Mypy：4 source files 通过（包含新增性能契约）。
- `git diff --check`：通过。
- 增量 selector：46 passed in 127.71s，命令如下。

```sh
uv run pytest -q tests/manager/test_baseline_source_inspection_scope.py tests/manager/test_execution_baseline.py tests/manager/test_paused_baseline_service.py tests/orchestration/test_continuation_store.py tests/orchestration/test_continuation_store_v2.py tests/context/test_source_inspection_scope.py --tb=short
```

其中新增 10 条覆盖真实调用点性能、独立调用/调用方生命周期及安全拒绝；已有 36 条
保留候选/草稿、精确审批、原生规则、receipt lineage、权限、字节上限和线程隔离回归。

独立 reviewer 审查同步 service/store 包装与 Host 调用位置，确认模型 resume 在 scope 外，
未发现新增 blocker。独立运行 standalone plan 与 continuation 2 条，以及负向/异常释放
selector 4 passed / 6 deselected in 15.35s；独立 Ruff 和 diffcheck 通过。

## 存量数据处置、风险与回滚

无需 Schema/SQL/持久化记录迁移，亦未改任何生产事实。存量 K1 plan/receipt/binding/批准
仍逐项完整校验。父任务可在服务空闲后受控加载该优化；继续需求仍依精确授权执行。
代码回滚恢复原性能开销，不影响数据。不能重置工作区、删除历史、重建需求或用
缓存替代权限/停止证明。全量测试留给用户，没有运行。
