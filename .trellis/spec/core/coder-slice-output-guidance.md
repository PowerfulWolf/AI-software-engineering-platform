# Coder 切片输出指导与固定拒绝分类

## Scope / trigger

修改 Coder Prompt、冻结工作切片或 native 输出接纳时适用。既有
[`delivery-preflight.md`](delivery-preflight.md) 的完整 partition 和候选门禁保持不变。
Prompt 必须说明真实 gate，不能只传切片 JSON 然后泛称实现完整计划。

这是一项前瞻缺陷修复。没有可用原输出的历史 `GIT_CONTRACT` 仍为具体子因未知，不能
将本次 fixture 的 slice failure 推断成原 K1 的真实失败原因。

## Signatures

```python
_coder_slice_output_guidance(request: AgentRequest) -> str
_coder_verification_guidance(request: AgentRequest) -> str
RequestPromptBuilder.build(request: AgentRequest) -> PromptPayload
ContextPromptBuilder.build(request: AgentRequest) -> PromptPayload
validate_coder_slice_output(work: CoderWorkSlice, artifact: Artifact) -> None
CoderSliceRejected(message: str, *, code: CoderSliceRejectionCode = INPUT_CONTRACT)
```

`CoderSliceRejectionCode` 是领域内的固定 Enum，不是新增 Artifact/Request/Schema 字段。
native adapter 从真实 gate exception 读取 Enum，映射为现有安全诊断的
`cause=WORK_SLICE; validation_rule=<fixed code>`。现有 `INVALID_OUTPUT`、nontransient、
output SHA-256/字节数以及失败接纳规则保持不变。native 诊断另附从固定 Enum 映射的
中文说明；普通 unknown `GIT_CONTRACT` 不新增推测说明。read-side 的通用角色失败过滤
需要另行对固定分类做中文映射，不能透传原始自由文本。

## Contracts

1. Request/Context 两 builder 在 system message 中使用同一个 typed helper；native
   直接继承其 `PromptPayload`。有切片的 native prose 要求遵循已安排切片；无切片的旧
   请求不增加切片指导或自行发明窗口。非 Coder 不收到 Coder 切片规则。
2. `later_step_ids` 非空时必须返回 `coder-progress`，即使所有 selected 步骤已经完成。
   不能返回完整 `implementation-report`、提前发布 candidate 或把草稿送给 QA。
3. progress 的 completed 保留全部 inherited completed；新增完成只能来自 selected 且
   在本轮真实核实完成。later 全部留在 remaining；尚未完成的 selected 也留在 remaining。
   completed/remaining 精确、互斥、完整覆盖已批准步骤。保留草稿/文件不证明 later 完成。
4. later 为空不强迫生成 candidate：仅在完整实施和原批准要求由 Coder 完成的验证实际完成后
   才能提供 provisional report，并经过原 CandidateCommitSkill/Git/权限/身份/lineage gate。
   未完成则继续报告 progress。required verification 的记录不能编造。
5. `changed_files` 仍是完整保留 dirty inventory，而不是只列本轮所选步骤的新增文件。
   步骤切片不扩大写路径，也不授权丢弃先前合法改动、创建额外预算或恢复未知结果。
6. 固定错误分类不能来自异常原文、模型输出、step ID、provider prose 或 CoT。
   `CoderSliceRejected.code` 只使用固定 Enum；native exception catch 不输出其 message。
   未识别的其它 `ValueError` 保留 `GIT_CONTRACT`，不猜测 slice 原因。
7. 不放宽 gate、补造 progress/candidate、自动修订输出或更改恢复/队列/人工批准。
8. Coder 的验证职责与批准 Plan 中独立 QA/Reviewer 的验证职责分开。仅缺独立验证环境，
   不能自行推导为 Coder 必须停止其余合法实施；继续实现选定步骤及精确测试入口，并如实
   记录未执行的检查、原因和风险。真实实施依赖、明确 Coder 必做条件、失败检查仍需处理，
   不能据此把未完成步骤标为完成。候选不等于交付通过，完整独立验收仍使用原候选与全部
   原测试等级。此规则作为共享 Coder system guidance 作用于未来输入，不注入任意 Context。

## Validation and error matrix

| Input / output | Fixed class / behavior |
| --- | --- |
| 无 slice 的旧请求、非 Coder | 无新增指导，原语义 |
| partial slice 提供完整实施报告 | `WORK_SLICE / PARTIAL_CANDIDATE`；无 candidate |
| progress 的 Task/revision 与 slice 不一致 | `TASK_BINDING` / `SOURCE_REVISION` |
| progress 不完整覆盖/存在交集 | `STEP_PARTITION` |
| progress 撤回此前 completed | `PRIOR_COMPLETION` |
| progress 宣称完成未安排步骤 | `UNSELECTED_COMPLETION` |
| gate 的 deferred 子检查 | `DEFERRED_STEPS`；仍在原检查顺序 |
| 其它 role kind 提供给 slice gate | `OUTPUT_KIND` |
| slice selection/next-window 输入错误 | 既有错误 message，固定默认 `INPUT_CONTRACT` |
| 其它未识别 Git `ValueError` | `GIT_CONTRACT`，未知具体子因 |

检查顺序保持不变：缺 deferred 通常先由 partition 或 unselected-completion gate
拒绝；不能为追求一个分类重排或放宽原确定性 gate。

## Good / Base / Bad cases

- Good：prior=1，selected=2，later=1；本轮完成一个 selected，progress completed=prior+1、
  remaining=另一个 selected+later，完整保留 dirty files 和原 HEAD。
- Base：later 为空但 selected 尚未完成，仍输出合法 progress，不强迫提交候选。
- Bad：旧草稿看似含全部文件，partial slice 输出 implementation-report；必须拒绝并保留现场。

## Tests required

`tests/agents/test_coder_slice_output_guidance.py` 使用实际 Request/Context builders、native
prompt compilation、fake process port 和真实临时 Git 仓库。覆盖 partial/final 指导、legacy、
保留继承完成的合法 partial progress、partial candidate/越界完成/撤回 prior/遗漏 partition、
安全固定诊断、完整dirty保留、最后切片的原候选门禁以及其它 Git 错误不误分类。
共享职责指导另覆盖有/无 slice 的 Request/Context/native、非 Coder 不增加指导、原 request
和权限不变，以及真实 native CandidateCommit 保留 NOT_RUN、原因与 evidence 而不产出 verdict。

相关增量回归：`tests/planning/test_execution_window.py`、
`tests/agents/test_negative_credential_prompt_guidance.py` 和实际 native/ordinary adapter 测试。
测试不调用生产 API、模型、MySQL 或服务，不能证明真实模型会遵循指导或原 K1 已恢复。

## 存量数据处置与回滚

无需改库：新 Prompt 仅作用于将来输入，新 subcause 仅作用于将来真实 typed 拒绝。
旧 failure/output/Task/Operation/approval/source/attempt 和 draft 不追溯重写。
原需求仍由其公开工程调查与精确审批恢复；不能因本补丁对未知旧执行直接重试。
在真实 role idle 后回滚对应代码提交并重新构造 Host；不删除旧事实或工作区。
