# 已停止、未接纳 Coder 草稿的统一受控接续

## Goal

原 K1 同一 Requirement 的真实 Coder 已完成并封存 FAILED/INVALID_OUTPUT、可靠 completed stop，但没有可用 artifact。保留完整合法草稿，复用既有 baseline 准备 → 精确工程批准并暂停 → 独立继续流程，允许新 Run 消费普通工作额度重新产出，不新增需求、恢复 Task 或第二套交付引擎。

## Observed facts

- Requirement `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`；Task `task_recovery_5536cf4e59ca28db0213bd719d50860d`；Run `run_cd17fc4c9d254fdf8ae13f19d0cc1fe9`。
- 原结果 `FAILED / INVALID_OUTPUT / transient=false / artifact=None`，诊断仅 `GIT_CONTRACT`。原 10529 字节 JSON 不再存在，不能补造具体子因。
- 真实 `completed / returncode=0 / output_present=true / owned_session_empty` 停止证明已封存；原 HEAD、branch、index 保留，没有 candidate。
- 当前 WorkItem 等待依赖且 lease 已释放；既有专用 progress 序号恢复及未知结果恢复均不接纳此类型。
- 现有错误输出拒绝本身保持正确；缺口是完整合法草稿没有用户可走的受控重新产出路径。

## Contract before implementation

继续使用 `CompletedCoderOutputUnavailableProof` 的既有 wire、完整原 outcome/start/stop、`completed_output_sha256` 与 `BaselinePurpose.COMPLETED_OUTPUT_RESCUE`。以原 `AgentFailure.code` 派生内部 typed reason，区分 WORK_INTERRUPTED 的未接纳未知产出与 INVALID_OUTPUT 的被拒产出；不得接受独立 reason/allow-invalid/已停止 Boolean。

对新 INVALID_OUTPUT 必须满足所有原 stopped/identity/claim/scope、无成功 artifact/真实接纳/candidate、nontransient、预算、完整 before/after/inventory/ignored-path、冻结权限、HEAD/index/branch、secret/链接/字节校验。原字节、失败原因、计费和 stop 均不可修改。任何新声明不替代安全证明。

同基线采用既有无目标准备；若明确更新源码则采用既有 SOURCE_REBIND 并审阅 native-rule 差异。新被拒产出接续必须工程授权、PAUSE 后另行 RESUME；不能通过 policy 自动放行。普通工作预留的 reason 由 proof 派生，所有 plan/facts/queue 消费强匹配，不退款。新 Run 正常领取 claim，并重新经过候选/独立 QA/Review。

## Acceptance

- [x] 先复现真实完成 INVALID_OUTPUT 无法准备的红测，再在实际 collector/service/queue 契约绿测。
- [x] 与旧 WORK_INTERRUPTED proof/plan/binding bytes、canonical digest 和历史读取兼容。
- [x] 两种原因严格区分，foreign/stale/missing/accepted/unsafe/exhausted 情况拒绝，无原记录变化。
- [x] 同基线 public prepare/PAUSE/RESUME 可完整重放；精确消费一次、新 work/run/claim、普通工作计费，旧失败保留。
- [x] JSON Schema 直接及嵌入定义与模型和新 reason 约束一致；重生成保留可执行 guards。
- [ ] 中文页面说明“报告未接纳、代码草稿保留、平台检查、批准后重新产出”；不会说历史结果已恢复、进度已验收或 QA/Review 已通过。
- [x] 只运行相关增量测试；单列存量处置、风险和回滚。

## Non-goals

不恢复原 raw JSON，不猜测 GIT_CONTRACT 子因，不纠正旧报告，不绕过原拒绝，不退款、扩权或改 Task 状态机，不自动 merge，不运行全量测试。Prompt/固定拒绝子码、Operation 摘要兼容由独立任务处理。

## Validation / rollback

选定 completed-output fixture、public baseline、schema、isolated MySQL pause/consume/release 和 shipped JS 当前恢复用例；实际 MySQL 测试只在独占守护的测试库执行。维护执行不访问生产写 SQL。公开执行前后核验原 Run/stop/Task/event 前缀/预算/完整草稿；回滚前受控 stop，已消费新 reason 时保留兼容 reader 并优先 forward fix。
