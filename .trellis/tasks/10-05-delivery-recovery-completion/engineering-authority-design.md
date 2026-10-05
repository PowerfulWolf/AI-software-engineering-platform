# 工程预授权、身份与真实恢复接线

## 契约与职责

新生产 Task 冻结 `EngineeringPolicy`，包含版本、Team/Project/Repository 精确身份、真实仓库根、可信本机工程主体和有界能力/预算。旧 Task 的缺省 `None` 不改变序列化摘要，不获得追溯授权。产品范围批准仍是精确 ProductSpec 决定；本机 `LocalOperatorPrincipal.require_duty()` 在服务边界区分产品与工程职责，Manager 不可自己成为工程授权者。

`EngineeringAdmission` 是 deterministic policy application，不是人工审批：它绑定冻结 Task intent、policy 全文及摘要、精确 plan/facts 摘要、能力集合、逐能力及总使用序号。独立 append-only 存储；不得构造 `RecoveryAuthorization.operator_id` 来冒充人类。既有人类 authorization 保持原字节、语义与读取契约。

## 真实接线

`TeamHost._resume_controller` 装配 `EngineeringAuthority`。候选验证新计划经现有 NativeVerificationFacts 重新校验后，允许冻结 policy 内的 verification refresh；Swift/PythonMySQL 的已注册执行器能力同时需要相应明确 grant。每次 QA/Reviewer 仍有独立实际 claim 和 invocation，所有 artifact 绑定同一 candidate SHA。未知调用不能在同 plan 重放，必须精确新计划并重新消费预算。

Manager 的源码前提修复建议由已有 `PrerequisiteRepairPlan` 封存。只在 request.paths 全部属于原 Task 写范围且未命中 deny、不变更原验收/命令/工具权限时适用工程 policy；走现有 Coder→QA→Review 服务，绝不直接修源码或自批 verdict。超 scope/凭据/安装/网络/新工具、预算耗尽均拒自动。

启动前与开发中的源码基线改变不能伪装成 runtime 平台升级。root 的同 Task 基线服务保留 `Task.base_ref` 原 intent，新增审计 execution-base binding 和 typed repository rebind；它通过 `EngineeringAuthority.admit(task, capability=EXECUTION_BASELINE_REBIND, plan_sha256, facts_sha256, store)` 获取一次精确工程 admission。迁移必须在无活跃进程、无 live claim、完整保存旧补丁、原 branch/worktree identity 不变条件下执行固定 Git 适配器，冲突交 Coder，不能用自动 successor 代替同 Task。普通 runtime 更新不迁移源码，不回写旧批准。

## 验证矩阵

| 输入 | 结果 |
|---|---|
| 新 Task 冻结 scope，精确当前 plan，能力和预算内 | 独立 policy admission，无 human authorization |
| 重放同 admission/facts | 返回相同记录，不再次计费 |
| plan、Task intent、policy/scope 漂移 | 拒绝、无新 invocation |
| 旧 Task 无 policy / 未注册 capability | 工程等待，不追授 |
| 原 scope 源码前提修复 | 正常 claimed Coder 与独立验收 |
| 扩权/安装/凭据/网络/业务变化 | 相应工程或产品精确决定 |
| admission 后调用结果未知 | 不重放旧 plan，保存现场 |

本模块测试仅离线/增量；MySQL 串行交 root；不创建生产需求或运行生产模型。
