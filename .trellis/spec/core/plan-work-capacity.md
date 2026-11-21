# 计划工作容量与 Coder 切片上限

## Scope / trigger

修改执行窗口、Coder 切片选择、Planner/Designer 输出接纳或生产窗口组装时适用。

失败模式（K1）：旧切片规则只按剩余工作额度平均分配待做步骤。16 个步骤、3 次工作额度、
预留 1 次返工时，每次 Coder 被分到 8 个步骤，在 1800 秒窗口内无法完成，只留下没有合法
progress/report 的草稿，随后每次中断都需要专用恢复路径。容量问题必须在规划阶段暴露，
而不是在 Coder 执行 30 分钟后以超时暴露。

## Signatures

```python
PlanExecutionWindow.max_steps_per_run: int | None   # 1..16，None 时不出现在 wire
PlanExecutionWindow.max_coder_runs: int | None      # 1..20，与上项同时出现或同时缺省
PlanExecutionWindow.step_capacity -> int | None     # steps_per_run × (runs − reserve_rework)
PlanExecutionWindow.validate_step_count(n) -> None  # 超出时抛 PlanExceedsWorkCapacity(ValueError)
bounded_coder_window(seconds, *, max_work_attempts) -> PlanExecutionWindow
DEFAULT_CODER_STEPS_PER_RUN = 3
```

## Contracts

1. 旧窗口不含容量字段，wire、digest 与切片语义完全不变；冻结的旧 Plan/Requirement 不追溯获得容量。
2. 新生产 Requirement/Plan 由可信组装写入容量（`bounded_coder_window`）；模型不能修改窗口。
3. 规划接纳：`PlannerStageService` 与联合路径 `compile_joint_plan` 都在接纳计划前校验每个 Task 的
   已批准步骤数；超出容量时拒绝并给出中文“需求过大，请拆分”原因，不启动 Coder。
4. 联合设计阶段在窗口有容量时告知 Designer 每个写入单元的步骤上限；放不下时提出 blocking_issue，
   不能把无关工作合并成超大步骤。
5. 切片选择：有容量且剩余额度能按上限覆盖全部待做步骤时，每次填满至上限（小计划一次完成）；
   否则（例如最后一个额度上的 QA 返工）退回旧的聚合规则，保证所有步骤可达，不留下无法完成的部分切片。
6. 所有内嵌 `PlanExecutionWindow` 的 32 个 Schema 定义保持一致，并与生成脚本输出一致。

## Tests

`tests/planning/test_execution_window.py`、`tests/planning/test_service.py`、
`tests/planning/test_joint_execution_window.py`。
