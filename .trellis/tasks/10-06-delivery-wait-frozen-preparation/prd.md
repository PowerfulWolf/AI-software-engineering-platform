# 工程等待调查使用原批准准备事实

## 目标与根因

修复用户点击“调查工程等待”时，因主 checkout 已升级导致 preparation 摘要变化而在检查环境前失败。
`TeamHost.inspect_delivery_wait` 的生产 prerequisite collector 错用了执行用的 current preparation
guard。调查应读取原 checkpoint 的 sealed preparation，并以当前 queued step 的精确 source 检查
真实注册 executor 的当前前提；平台运行版本、目标 main 和批准 Task 输入是不同事实。

## 契约与范围

- 保持 `inspect_delivery_wait_prerequisites(task, step, checkpoint) -> DeliveryPreflightReceipt` 不变。
- 仅调查改用原 sealed preparation，仍校验 checkpoint、sidecar、profile、binding、compiled spec、
  已接纳 Plan、Task/队列身份与当前 source。既有 execution-baseline binding 的 intent 校验不得弱化。
- 通用执行 `_facts_for_checkpoint` 的 drift 拒绝不变；不静默改变原审批、原生规范或 Task.base_ref。
- 原准备记录缺失、篡改和 source 错配必须拒绝，不 fallback 当前 prepare。
- 本轮只修代码并装载；不代用户 POST 调查、批准、继续或更新基线。

## 允许路径

`src/ai_software_engineer/manager/production_backend.py`、
`tests/manager/test_production_execution_baseline.py`、
`.trellis/spec/core/engineering-authority.md` 和本任务目录。

## 验收与增量验证

- 通过公共 TeamHost，在隔离 MySQL 与临时真实 Git 的未调用 Coder preflight 等待中修改主分支及
  原生规范，调查仍绑定原准备/source，产生真实 prerequisites 调查记录，Task 和队列保持等待。
- 缺失/损坏 sealed preparation 和 stale source 仍安全拒绝，无模型调用、无重建批准事实。
- 既有 baseline investigation 与 sealed preparation 的边界回归通过。
- `.venv/bin/pytest tests/manager/test_production_execution_baseline.py`（隔离 fixture 数据库）、
  `tests/manager/test_sealed_preparation.py`、`tests/manager/test_delivery_wait.py`；改动文件 Ruff/mypy。

## 存量数据处置

原 K1、Task、source、批准和 FAILED Operation 保留；无需改库。旧失败没有有效调查 proof，
不能改为成功或人工解除等待。服务装载后用户在原需求重新点击调查，生成新 immutable proof。
只有新调查提供精确可用的恢复选项时才按页面继续；真实环境缺项先处理后重新调查。
含新原生规范的最新版 source 更新仍需要独立规范/范围处理，不能以本修复绕过。

## 回滚

回退本次平台修复提交并在交付操作空闲时重新装载服务；不回退数据库、需求或审计历史。
