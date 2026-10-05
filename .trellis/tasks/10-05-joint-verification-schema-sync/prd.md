# 联合验证计划静态 Schema 与模型精确同步

## 目标与已确认问题

恢复流程增量测试暴露既有静态 wire 漂移：requirement-create 多空 `$defs`；
requirement-checkpoint 与 joint-execution-plan 的 PlanTestItem 缺少模型已支持的
verification_argv、planned_test_files、verification_inspection、controlled_capability_kind。
因 additionalProperties=false，合法验证计划可能被静态契约拒绝。

## 范围与验收

- 只同步受影响静态 schemas，保持 `$id`/`$schema` 和现有字段语义。
- 不修改领域模型、运行审批、产物 bytes 或放宽 exact Schema/model 一致性断言。
- 检查所有复用 PlanTestItem 的静态契约，仅修已证实的同类嵌入漂移。
  实际包括 knowledge-stage-workflow 与 plan-work-graph；前者还缺已存在的
  JointCheckpoint.coordination 可选字段，后者缺 PlannedVerificationInspection 依赖定义。
  同组增量 parity 确认 knowledge-delivery-admission 仅多空 `$defs`，同步去除。
- 同步 docs 与 code-spec；exact 联合 schema/model contract 与相关增量测试通过。
- 不运行全量测试，不修改生产 SQL/journal/verdict。

## Red 证据、验证和回滚

`.venv/bin/python -m pytest -q tests/manager/test_joint_contracts.py::test_joint_schemas_are_in_sync_with_models`
在原 HEAD 794b7c4 失败：requirement-create.schema.json 多 `$defs: {}`。
独立只读逐模型 diff 同时发现两处 PlanTestItem 四字段缺失。

允许路径：schemas/ 下精确受影响文件、docs/architecture/contracts.md、
.trellis/spec/core/python-runtime.md、本任务目录。
新增契约验证允许 tests/manager/test_verification_schema_embedding.py。
回滚：回退静态 Schema/文档代码；旧产物及 durable 历史无需迁移或改库。
