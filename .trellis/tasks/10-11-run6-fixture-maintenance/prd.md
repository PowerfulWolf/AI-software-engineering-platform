# K1 run6：一次性、可审计的外部测试维护

## 问题与目标

K1 原需求的 Coder 第 6 轮确实在本地执行时限后停止。原生 capture-start 和
capture-stop 可校验，进程组已停止，但随后完整源码捕获在一处测试输入被敏感字面值
检测拒绝，导致没有 continuation receipt。原结果仍未知，不能补造 outcome 或完成产物。

用户已委托维护和交付，当前工作把外部测试修改明确记录为人工介入，再交由公共 baseline
proposal/approval 路径核验真实现场和更新执行基线。它不是 ASE 自主修复能力或交付批准。

## 精确范围

- Task：`task_recovery_8ca06fa0aec236ab940597ad1482bfc8`，revision 8，attempt 6。
- Run：`run_1b8ce9675c6b4f1fbafe51b3cd2cb50f`。
- WorkItem：`work_6bbbcd2f142d64efbd83f17ec50a992fd7ef552414dd997361bc793bc3c57025`。
- 唯一源码路径：保留 Coder checkout 的 `tests/learning/test_bounds_retry.py`。
- 唯一内容变化：用另一个独立 fixture ledger 的真实非空 claim token 作为未知令牌，
  替代固定假令牌字面值。保留未知非空、空值、过期 fence 的拒绝断言。
- 平台源代码、扫描器、其他 K1 文件、Task/队列/预算、执行结果和 verdict 不在写范围内。

完整 exact plan、前后源码和 diff 摘要见 `plan.json`。仓库里的 `correction.patch` 是通用
脱敏展示；完整原 bytes 只可在 apply 时保存到受控 sidecar 私有审计目录。

## 验收标准

1. prepare 只读生产事实，通过原停止证明、任务锁和 idle-task fence 后冻结完整计划。
2. apply 必须收到 exact plan digest 和非空授权引用。先写完整审计与
   `HumanActionEvent(MODIFY_TESTS)`，再仅原子修改该文件，保持 0644。
3. 当前状态、原历史、原 HEAD、分支、index 和其他文件不得改变。
4. 未知前态、授权不匹配、源数据漂移或 symlink 拒绝；仅完整审计支持的 exact 后态允许崩溃重放。
5. 隔离复现原完整捕获拒绝；修正后完整 capture、wire roundtrip 和 verify 通过。
6. 隔离执行目标负向测试和整个所在文件，包含真实本地子进程并发用例，无跳过。
7. apply 本身不得调用 HANDLE、resolve/resume 或启动模型；后续由公共 baseline 操作负责。

## 验证命令

在仓库根目录使用已有 Python 3.12 虚拟环境，`PYTHONPATH=src`：

```text
python .trellis/tasks/10-11-run6-fixture-maintenance/fixture_correction.py prepare
python .trellis/tasks/10-11-run6-fixture-maintenance/verify_isolated.py
ruff check .trellis/tasks/10-11-run6-fixture-maintenance
ruff format --check .trellis/tasks/10-11-run6-fixture-maintenance
MYPYPATH=src mypy --strict .trellis/tasks/10-11-run6-fixture-maintenance
git diff --check
```

仅两个精确 pytest selection；不运行全量测试。隔离验证创建 disposable shared clone，
完整复制当前 28 项 dirty bodies，仅测试进程访问该副本，结束后清理。

## 存量数据处置与回滚点

prepare 和隔离验证不改生产事实。apply 的唯一源码写入会留下不可变前后正文、diff、授权、
人工介入事件和完成记录，不直接改库。原执行和失败历史保留，自治归因必须计人工介入。

后续公共 `PROPOSE_EXECUTION_BASELINE` 可在不启动模型的情况下核验停止现场并封存；
对 exact proposal 执行 `EXECUTE_EXECUTION_BASELINE(continuation_mode=pause)`，更新基线后再独立
批准 `RESUME_EXECUTION_BASELINE`。不能先 HANDLE，因为成功处理会立即继续旧基线执行。

任何前提或后验失败立即停在原需求，不重建、不丢弃草稿、不自行清空。before.py 是回滚证据，
恢复原 bytes 仍需独立授权并追加人工审计，不能删改已有记录。
