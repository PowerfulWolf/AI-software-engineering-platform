# Manager 跨阶段受控协调与可配置执行预算

## Goal

补齐已有 Manager 验证协调模型调用的故障重试与时间扩容，并将基于证据的
Manager 诊断协调扩展到跨阶段阻塞；所有执行仍受 typed policy、精确审批和独立验收约束。

## Requirements

- 明确服务故障与本地执行时间窗口耗尽分别持久化，不推断超时一定意味着有效思考。
- 时间窗口按几何扩容，初始窗口、扩容与故障次数的边界可配置；不得无限重试。
- 现有 Manager 模型调用使用角色路由，纳入可恢复的预算记账；纠正文档和设置 UI 的过时描述。
- Manager 可跨阶段读取已验证阻塞事实并提出受控处理方案，不获取 store/shell/审批或越权派发能力。
- 保持 Product 精确批准、Design/Plan lineage、Coder/QA/Reviewer 独立验收和既有终态恢复规则。
- 单 Agent、当前目录修改，保留其他任务改动，仅增量测试；授权实现完成后提交本次文件。

## Baseline facts (before implementation)

- `CandidateVerificationEntry.coordinate` 通过 `TeamRole.MANAGER` 创建模型客户端。
- `coordinate_verification` 当前固定 240 秒，最多两次输出修正，不使用上游扩容记账。
- Product/Design/Plan 已分别记录 transient 与 capacity timeout，但窗口和边界目前为常量。
- 现有 Manager recovery 对 typed 能力和人工批准的约束可复用，不引入任意工具执行。
- `.trellis/scripts/` 初始化脚本缺失，手工维护本任务文档。

## Acceptance criteria

- [x] 配置、Schema、Settings API/UI 与运行时采用同一预算契约。
- [x] Manager 服务故障、本地超时、无效输出与人工阻塞分开处理；重启不丢失计数。
- [x] 相同阻塞证据幂等复用；不同阶段/修订/审批作用域不能复用旧建议。
- [x] 跨阶段建议只能选择该阶段可用的受控动作，不能跳过审批、重置终态或生成 verdict。
- [x] 增量正向、边界、拒绝及恢复测试通过。
- [x] 明确存量数据处置、回滚和操作说明。

## Approved decision

- 用户已批准自动诊断及已授权、预算内的安全重试；代码修复、范围变化和新增权限仍走现有审批。
- 完成后提交并推送；启动暂停中的真实需求前另行向用户确认授权。

## Out of scope

- 单 Task 并行、多 Agent 委派、通用 shell、自动审批、自动 merge、自动修改生产历史。
- 安装新基础设施、无限循环、宣称超时证明模型仍在思考。

## Validation / rollback

- 先 contract/fake adapter 测试，再增量 lint、typecheck、相关 Python/JS 测试。
- 不调用生产模型、不重启服务、不迁移真实 Requirement；恢复入口必须保持审计历史。
- 回滚仅限本次提交；新增持久化字段须定义旧记录兼容规则。
