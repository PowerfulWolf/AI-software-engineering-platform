# 实现说明

恢复后继 Task 以前只复制原始 retry/max_attempts，没有正常派发时冻结的工程授权和续跑
授权。这次把目标授权作为新 RecoveryPlan 的显式契约，而非在执行时隐式读取当前配置。

- `RecoveryTargetAuthorization` 绑定原 Task ID、完整 wire SHA、max_attempts、typed
  source_retry_policy、固定 bounded_local EngineeringPolicy 和按该预算精确派生的 v2
  continuation。无 retry 的旧 Task 不能获得 v2。扩张 grant、总额度、版本、scope、来源或
  continuation 预算均拒绝。
- `RecoveryPlan.target_authorization` 缺省 None，嵌套 model_dump/model_dump_json 中也省略。
  新授权进入新计划摘要和 successor Task ID，旧批准不能用于新授权。
- Native entry 只在可信 ENGINEERING 主体存在时签发，scope 取真实准备事实和已注册
  Project。没有该主体或仅 PRODUCT 职责则省略，不创建默认本机主体。
- Current verifier 在读取注册表后核对完整 Team/Project/Repository/root 和原 Task 全文及
  冻结预算。Builder 再次核对目标准备 scope，只传递已批准计划的两项 policy。
- RecoveryTaskRecord 验证两项 policy 和冻结预算与计划完全一致。缺少目标授权的旧计划
  不允许在 Task record 中偷偷注入新 policy。
- 窄 Schema 同步脚本仅添加新字段及传递定义，保留旧定义和手写 allOf/权限限制。未新增
  执行器：继续走既有 backend.run_prepared_allocation 的角色执行、续跑和验证装配。

本任务未修改 app.js、workspace_snapshot、Knowledge timeout、生产状态或其他 worker 文件。
组织规范由根代理统一更新，独立 reviewer 和提交/部署也由根代理负责。
