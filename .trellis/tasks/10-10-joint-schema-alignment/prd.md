# 联合需求 checkpoint 的精确 Schema 对齐

## 目标与根因

`ProjectDeliveryCheckpoint.next_action` 使用 Manager 的 11 值枚举；当前静态
`requirement-checkpoint.schema.json` 被替换为 disposition 的 8 值同名枚举，拒绝合法
原生子交付。`sync-manager-schemas.py` 的完整模型生成结果正确；后续 legacy rescue
同步器按短 `$defs` 名称归并多个不同模型图，将 TeamSnapshot 的 disposition 枚举覆盖到
联合 checkpoint。不得通过合并两个枚举或放宽 Schema/测试绕过错误。
一次只读枚举全部静态 Schema 的 `ProjectDeliveryCheckpoint` 图发现同源触点只有两处：
`requirement-checkpoint` 与 `knowledge-stage-workflow`。后者的 `StageWorkflowProof` 完整图
同样只在 `DeliveryNextAction` 与真实模型不符，现纳入相同修复范围。

## 验收与允许范围

- 静态联合 checkpoint 与 `JointCheckpoint.model_json_schema()` 精确一致。
- 静态 knowledge stage workflow 与 `StageWorkflowProof.model_json_schema()` 精确一致。
- 子交付的 next-action 引用 Manager 全部 11 值；合法交付、人工等待、完成输入均可验证。
- disposition 专属值与未知值在 JSON Schema 和 Pydantic 的子 checkpoint 字段均被拒绝。
- 在临时目录依次运行 Manager 和 legacy rescue 同步脚本后，两份完整契约仍精确一致，
  disposition 保留自己的 8 值契约；重复同步幂等。
- 只修改 allowlist，保持 domain/wire 模型、审批和生产 facts 原样。
- 增量验证：joint contract tests、相关 legacy rescue Schema tests、Ruff、strict Mypy、diff check。
  同时运行现有 knowledge schema parity tests；没有忽略或删除既有断言。

## 存量数据处置、部署与回滚

无需改库或改写旧 JSON/hash。模型从未改动，修复只纠正导出的验证契约；合法原 checkpoint
重新验证即可使用。旧工作区、失败记录和 exact 审批全部保留。部署与原需求继续由 root
通过公开交付入口操作，不由本任务执行。回滚本次 Schema、同步脚本和文档变更即可；
回滚会恢复错误的静态验证行为，但不会改变历史事实。
