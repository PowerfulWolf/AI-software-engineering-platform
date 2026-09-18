# T051 验证与交接

## 原因与修复

`ProductionJointBackend.reconcile()` 经 `delivery_runtime()` 正确读取恢复后的 preparation；
`deliver()` 却再次经 `_entry()` 从父需求原始 preparation 构建 runtime，随后 `start()`
reconcile 当前原生 checkpoint，抛出 `ValueError: delivery preparation checkpoint drifted`。
这使原生交付 DONE 后父需求无法从 DELIVERING 进入 INTEGRATING。

已有 child 现在通过同一 `delivery_runtime()` 读取当前 status；DONE 不执行角色，父服务将
新观察值追加到 journal 后执行 integration。没有 child 时保留原有确定性 start 路径。
未改变 Task 状态机、Schema、审批或 verdict 契约。修复同时补齐受影响测试的 union 类型断言。

## 定向验证

测试使用独立 `ase_delivery_20260917_tests` MySQL 数据库、临时 Git 仓库和 fake adapter，
没有使用生产库作为测试库，也没有启动真实模型。

| 命令（已设置独立 ASE_TEST_MYSQL_DSN） | 结果 |
| --- | --- |
| `.venv/bin/pytest -q tests/recovery/test_resume.py -k joint_scope --tb=short`，修复前 | 1 passed / 1 failed；完成分支精确复现 preparation checkpoint drifted |
| 同上，修复后 | 2 passed / 6 deselected，189.08 秒 |
| `.venv/bin/pytest -q tests/e2e/test_joint_delivery.py tests/e2e/test_project_revision_preparation.py --tb=short` | 5 passed，76.34 秒 |
| `.venv/bin/pytest -q tests/manager/test_joint_contracts.py tests/manager/test_joint_planner_feedback.py tests/manager/test_joint_designer_feedback.py tests/manager/test_requirement_retirement.py` | 49 passed，1.54 秒 |
| `.venv/bin/ruff check src/ai_software_engineer/multi_directory/production.py tests/recovery/test_resume.py tests/recovery/test_native.py` | 通过 |
| `.venv/bin/ruff format --check src/ai_software_engineer/multi_directory/production.py tests/recovery/test_resume.py tests/recovery/test_native.py` | 通过 |
| `.venv/bin/mypy src/ai_software_engineer/multi_directory/production.py tests/recovery/test_resume.py tests/recovery/test_native.py` | 通过 |
| `git diff --check` | 通过 |

新增完成分支断言：重建 Host、原生使用已批准的新 preparation、父联合 DONE 且有集成证据、
剩余角色调用只属于第二个未完成仓库、重复 resume 不新增任何角色调用。
原有再次中断、首次 child、父 publication 崩溃、失败集成和旧需求固定基线用例均通过。

## 存量数据处置

- 目标需求：`delivery_multi_b7878e4343474b1114cb62e866776f3bda993ae4`。
- 父：sequence 14 / DELIVERING，digest
  `e243fd21e8ff85b02782b31e6aebf935ae56b74a85e4ddf1f50b605c6652d663`。
- 子：`delivery_bd9f195965dab7baae883da6d9d6774d`，sequence 55 / DONE，digest
  `85a3e698892d08e96428ddc8ea3a430c78a4e3c1dc74c61d2f1b1f912476803c`。
- candidate：`d337b6bf6b42788876b9296896081ae92030e0f3`；QA PASS 已复用，Reviewer APPROVE。

用只读 probe 验证真实 checkpoint：原先原始 runtime 报 preparation drift，恢复 runtime 可读到
DONE；修复后 `deliver()` 返回同一 sequence 55。probe 禁止 start/resume/approve、禁止新建
worktree，并跳过 dispatch authority 的 schema 初始化，只允许读取已有分配；父/子 journal
前后所有 JSON 哈希相同。没有重置 Task、修改审批/verdict/Operation，或推进生产父需求。

无需改库。用户从当前平台代码目录沿用原配置重启 Console，刷新原需求后点击一次“继续交付”，
平台应吸收已完成 child，再运行联合集成；通过才进入 DONE。此次不需要新验证计划或重新
执行 Coder/QA/Reviewer。详细命令见 [操作闭环](../../../docs/operator-feedback-loop.md)。

## 风险与回滚

生产候选的联合测试尚未运行，不能预先宣称整个需求已交付。若出现新的集成错误，保留 Operation
ID 和错误记录继续排查。现有工作区其他未提交改动全部保留，本次未提交或重启生产服务。

回滚只撤回 T051 的 `deliver()` runtime 选择与相关测试/文档变更，再重启；不要回退其他任务
或改写 journal。旧逻辑会重新出现该阻塞，回滚后停止重复继续交付，等待兼容修复。
