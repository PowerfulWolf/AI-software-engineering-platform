# T050 Technical Design

## Contract

`CandidateVerificationInputs` 增加可选的 `accepted_qa`，包含 sealed QA artifact ID 和 digest。该字段只能由
native source reader 从 candidate 后第一个 `qa_passed` StateEvent 推导，调用方不能自行选择任意 QA。

`CandidateVerificationRunner` 在 `accepted_qa` 存在时读取并验证 event、artifact、candidate、parent、
criteria、PASS 和 producer role，然后跳过 QA，直接创建 Reviewer request。不存在时保持原流程。

`CandidateVerificationCompletion.qa_invocation_sha256` 在复用 QA 时为空；store 以 plan 中的
`accepted_qa` 和 artifact digest 验证 QA，Reviewer 仍必须绑定本 plan 的 durable invocation。

## Validation Matrix

| Case | Result |
|---|---|
| candidate 后有精确 `qa_passed` event 与 sealed PASS | 新 plan 绑定 QA；只调用 Reviewer |
| 无 `qa_passed` event | 正常调用 QA → Reviewer |
| QA ID/digest/candidate/parent/criteria 漂移 | fail closed，零 provider 调用 |
| QA 非 PASS 或 producer 非 QA | fail closed |
| Reviewer 再次中断 | plan at-most-once；下一个 plan继续绑定同一有效 QA |
| Reviewer 产出 verdict | completion 复用 QA fact并绑定新 Reviewer invocation |

## Rollback

回滚本任务代码和 schema。历史记录不变；旧版本忽略不了新增 plan，因此回滚后应停止批准新格式 plan，
重新走旧版候选验证计划。
