# Implementation log

## Initial diagnosis

- `ase request status <delivery>` 在无默认 Project 的多 Project 配置下未传 Delivery ID，直接报“select a Project”。
- `_facts_for_checkpoint` 将 preparation digest 漂移抛为裸 `ValueError`，`_guard` 只保留异常类型，CLI/页面无法理解原因。
- Team View 对候选上下文预算、认证、限流、超时和非法 evidence 等稳定事实统一显示“执行失败”。

历史 durable facts 仅用于验证和展示，不直接修复；真实 K1 继续交付需以当前 preparation 创建新的精确 recovery/verification lineage。

## QA 增量测试约束

候选复核期间发现 Codex QA 忽略了已有的“默认只跑聚焦测试”提示，启动了无选择器的
`pytest -m not mysql` 全仓测试，违反了操作者把全量回归留给人工执行的约束。QA prompt
现明确要求每次 pytest 都带 `tests/` 下的文件或节点选择器；缺少验收映射时返回
`INCREMENTAL_TEST_SELECTION_REQUIRED`，不得自行扩大到全仓。该修复只改变后续 Agent 的
可执行指引，不修改已经封存的 run、artifact 或 verdict。

## QA/Review 命令边界

真实候选复核证明仅靠 prompt 约束不足：Responses Agent 仍可能通过
`pytest -m not mysql`、`pytest tests` 或 `uv run python -c 'pytest.main(...)'` 启动全量收集，
导致用户要求的增量测试门禁失效。后续 QA/Reviewer 的 Responses 工具执行器启用机器级
`require_focused_tests` 校验，要求 `tests/` 下明确的测试文件或节点；目录、仅 marker、无
选择器和动态 `pytest.main` 在进程启动前拒绝，并返回中文原因。旧执行记录、候选、审批和
verdict 不修改；回滚仅需在无活动角色时回滚平台提交并重启。

## 候选验证器误选 Swift

最新验证计划暴露了另一个平台缺陷：平台自身 `RepositoryProfile` 包含 Swift fixture，
`_task_commands(profile)` 因此带有 Swift 命令，候选 capability 仅凭命令集合错误选择
`codex_sandbox_swiftpm_v1`。Python 候选的 QA 随后执行 `swift build/test`，因没有
`Package.swift` 生成环境错误，导致真实 Python 增量测试根本没有机会运行。已让候选命令
编译先移除 profile 继承的 Swift 命令，仅当候选 revision 自身存在 regular 顶层
`Package.swift` 时重新加入。保留本次 QA FAIL 及所有旧事实，下一次必须重新 propose/approve
精确计划，不能重放本次计划。

## 终态候选在基线漂移后的继续路径

验证 K1 候选时发现，旧 Delivery checkpoint 的 preparation digest 漂移会在
`retry_interrupted_stage` 先于候选验证完成被调用，导致已封存的 QA/Review 结果无法路由到
Coder 修复。`DeliveryResumeController` 现在先在当前候选作用域读取唯一的
`CandidateVerificationCompletion`，再交给既有 remediation/adoption 门；没有 completion 时
仍走原生重试。该顺序只改变读侧路由，不修改历史 Task、StateEvent、Artifact、Approval 或
completion。新增增量回归覆盖 stale native retry 被跳过的事实。
