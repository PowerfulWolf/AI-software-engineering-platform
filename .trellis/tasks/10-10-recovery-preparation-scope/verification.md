# 验证记录

## RED 与测量

先新增 contract tests，再修改 production：

```sh
.venv/bin/python -m pytest -q tests/recovery/test_preparation_inspection_scope.py \
  -k 'builder_reuses or allocator_shares' --tb=short
```

2 failed / 1.65s，失败仅在扫描次数断言：初始 source/generic fixture 的 Builder 7/42、
allocator 30/180；此前 fresh facts/capture/双 fence 断言均通过。

随后加强为真实非空完整补丁，使用独立 Python 进程内暂时移除六个方法的 decorator，
不改磁盘文件，不访问生产。实际完整 scanner RED 计数：

| 场景 | source misses | full patch misses | generic regex subn |
| --- | ---: | ---: | ---: |
| Builder baseline | 21 | 19 | 42 |
| Allocation baseline | 107 | 97 | 180 |
| 同步作用域修复后的每次调用 | 1 | 1 | 6 |

该 RED 2 failed / 2.14s，均在性能断言失败。Builder 的 10 facts/2 capture 和
6 plan/2 authorization getter、allocator 的 40 facts/8 capture 和33 plan/14 authorization
getter，以及前后 fence 均保持原计数并先通过。不是生产耗时采样。

## GREEN 与增量回归

- 新增文件完整运行：12 passed /5.36s。
- 授权、Task record、source/generic cache 及新增测试的增量组：66 passed /6.12s。
  执行命令如下；adapter 文件被筛除后，另使用精确 node 补测所需两个 admission 用例。

```sh
.venv/bin/python -m pytest -q tests/recovery/test_preparation_inspection_scope.py \
  tests/recovery/test_authorization.py tests/recovery/test_task_record.py \
  tests/context/test_source_inspection_scope.py tests/context/test_generic_redaction_scope.py \
  tests/agents/test_codex_cli.py \
  -k 'not test_platform and not test_coder and not test_review and not test_qa and not test_transient and not test_denied and not test_command and not test_native and not test_secret and not test_codex' \
  --tb=short
```

```sh
.venv/bin/python -m pytest -q \
  tests/recovery/test_terminal_source_inspection_scope.py::test_proposal_reuses_exact_full_text_but_repeats_fresh_capture_and_fact_reads \
  tests/agents/test_codex_cli.py::test_recovery_seed_admission_is_consumed_before_review_remediation \
  tests/agents/test_codex_cli.py::test_rejected_recovery_seed_admission_is_not_consumed \
  --tb=short
```

4 passed /15.89s，包含两个精确低容量 terminal proposal 变体，以及实际 Codex adapter 的
one-use initial admission /拒绝不消费回归。所有模型/外部 Git/MySQL 操作使用明确离线 seams
或临时 Git；没有实际模型或生产调用。

## 静态质量

四个 production 模块和新增测试：Ruff check、Ruff format --check 全部通过；
strict Mypy：Success: no issues found in 5 source files；git diff --check 通过。
Production diff 仅四条 import 和六条 decorator；所有原方法体、核验顺序和 fresh calls 未改。
未运行全量测试，未提交、推送、重启、审批或修改生产数据。

## 存量与回滚

无迁移或改库。原需求/Task/计划/审批/失败历史与现场保持；root 负责独立审查、提交、部署和
同需求公开路径验证。本任务不是平台已无 bug 或当前生产审批已完成的证明。
回滚这六个 decorator 与四条 import，并通过原受控部署流程加载，可恢复原成本；不删除
任何 durable records 或工作区。

## root 独立复核

复核四个生产模块的全部差异：只有六个同步方法的scope与导入，原方法体/前后fence/
getter顺序保持，没有包裹执行入口、模型或异步生命周期。独立选择后fence正文漂移、已扫描
plan篡改、provider前scope释放和失败不发布invocation四项回归：4 passed，8 deselected。
范围、缓存容量及存量边界符合当前规范，没有阻断发现。运行服务仍在处理已批准的原操作；
此次独立验收不代表补丁已部署或原需求已交付。
