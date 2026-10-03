# Design

`PRODUCTION_DELIVERY_CONTEXT_BUDGET` 是生产 backend、RuntimeConfig、ContextBuilder 和恢复记录共享的唯一生产输入预算。将其从 128,000 提升到 256,000，继续使用 `BoundCandidateSource` 的完整候选快照和 ceil(chars/4) 最终提示检查。旧 Context/计划仍按其冻结预算读取；更新后的验证计划绑定新平台 baseline 和新 Context manifest。

Validation matrix:

- Good: candidate final prompt <= 256,000; model call may proceed.
- Base: existing 128,000-sized candidate and small delivery retain identical role/artifact contracts.
- Bad: final prompt > 256,000, source/digest mismatch, or truncated required source; refuse before provider call.
