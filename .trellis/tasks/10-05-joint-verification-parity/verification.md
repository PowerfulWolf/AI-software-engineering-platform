# 验证记录

## 最终增量结果

2026-10-05，源码冻结后的相关增量测试：**165 passed in 54.19s**。没有运行全量测试。
独立 checker 在冻结源码上复跑同组测试：**165 passed in 54.37s**，并通过 Ruff/Mypy/diff 检查。

```sh
.venv/bin/pytest -q \
  tests/manager/test_joint_verification_admission.py \
  tests/manager/test_joint_verification_recovery.py \
  tests/manager/test_joint_designer_feedback.py \
  tests/manager/test_joint_contracts.py \
  tests/manager/test_joint_planner_feedback.py \
  tests/manager/test_production_agents.py \
  tests/knowledge/test_joint_recheck.py \
  tests/web_console/test_manager.py
```

Ruff 检查本任务九个源文件和两个新增 test 文件，结果 `All checks passed!`。
Mypy 检查九个源文件，结果 `Success: no issues found in 9 source files`。
`git diff --check` 通过。具体文件与命令见 `implement.md`。

## 覆盖的契约

- red：新增 publication parity contract 首先因 admission 缺失失败；原生真实 validator 对
  inspection + integration/security 已拒绝，而旧联合 validate_for 仍可读取封存设计。
- fake contract：合法/非法 inspection、中文精确 acceptance 反馈、真实 verification_argv 保留
  原 levels、三轮删除 level 不能绕过、原 unit/验收映射不能移除、旧 digest 可读。
- 稳定纠错历史：同一批准下知识等待和公开 recheck 后，较弱新 feedback 仍不能抹掉原要求。
  合法非数字验收 ID 精确保留；非法 ID、untrusted error-like 策略文本不能扩大恢复权限。
- production composition fixture：实际 ProductionProjectDeliveryBackend / DerivedStageInputs /
  UnifiedProjectEntryService 录入 FAILED / INVALID_OUTPUT 原生 receipt，再由只读 proof
  重新加载 Product/Design/native 记录，重建 Run 输入和 Context 谱系。没有模拟成功 verdict，
  无需 SQL 连接或角色执行。
- 恢复反向 gate：scope/source/approval/request/context/receipt、隐藏旧 child、历史 Task/
  dispatch/candidate/accepted handoff、预算和 Engineering duty 不符均拒绝；不发布 successor。
- 全 scope 的既有 baseline 都必须干净且源 SHA 精确匹配，包括没有 current child 的 unit。
- 公开 Host 与实际 ManagerConsoleAdapter Continue 缺失 baseline 回归：零 reconcile/factory
  调用，不创建 baseline，Project bytes、Git worktree registration 和 refs 不变，拒绝原因中文。

初轮 fixture 曾误选另一 unit 的基线，已精确修正。既有静态 Schema drift 由 root 在独立任务
提交 `19de30a` 修复；本任务没有改 Schema。最终增量包含 joint exact Schema parity，全部通过。

## 存量数据处置

root 在最终冻结源码上对真实 K1 checkpoint
`cf43013b4bb61038a2d65b0e4b0f74bdbdf8297a26d73e9f01e42d67f5543be9` 复验通过。
Design `8e239ef83f5bf71c7698c3eee94fb2a0b50b101b6551531d0feef1083d1d7c56` 与真实 native failed
receipt `ccad146b900feb82f7b9a519e0ab1db85ccf0fe474039c7cf86bdb5e4c59e817` 精确吻合；全部
scope 的 source/baseline 干净。Project 中 4401 文件的前后 SHA inventory 一致，零写入。

无需改 SQL 或 journal。独立审查通过并在生产空闲发布后，由 root 走公开 exact CONTINUE；
服务在锁内重新核验 proof，追加新 DESIGNING checkpoint，保留原批准、范围、预算与失败历史。
生产发布、Operation 及 successor 结果由 root 追加，本 worker 未操作生产、提交或推送。

## 风险与回滚

本次验证证明窄上游纠错和公开入口契约，不等于 K1 已交付或平台没有其他 bug。
任何已产生原生执行 work 的需求都不适用此路径，保持既有工程恢复流程。
回滚仅在空闲时还原本任务代码，保留新旧不可变记录；旧 Host 若不能理解新 successor，须升级
后继续，不能删除历史、退预算或将旧被拒设计改成有效产物。
