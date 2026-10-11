# 契约与验证

## Typed boundary

`KnowledgeInvocationJournal(records).call(binding, phase, *, client, instructions,
input_payload, output_schema, timeout_seconds) -> StructuredModelResult`。

`KnowledgeInvocationIntent` 包含 binding、phase、request_sha256、timeout_seconds、created_at、
intent_sha256；immutable key 为 binding.run_id + phase。请求摘要覆盖 instructions、完整 input
及 output schema，不在新的审计记录复制密钥或原始模型输出。

`KnowledgeInvocationOutcome` 引用 exact intent、终局结果/typed error、所有实际 structured
admissions 及对应 native/HTTP receipts；结果仅保存经 redaction 检查的 bounded JSON。
成功和失败记录均具有自己的 SHA-256。单独的 route 记录先落盘，防止 outcome 写失败时
真实 stop 一并丢失。生产权限仍由调用者真实 Worker/stage/Manager gate 持有；记录本身不授权。

## 发布与重放

1. 同一 intent 若已完整成功，校验 exact request 并重放结果，不调用模型。
2. 完整失败重放原 typed error，不在旧 run 内重新执行。
3. intent 已存在但没有 outcome：保留记录，抛执行不确定，不猜测未启动。
4. 新意图原子发布完成后才调用模型；每个实际 route 的 admission 在进程/HTTP调用前保存。
5. native stop 由 owned runner 提供，HTTP只代表本地同步 transport 返回。
6. observer/记录失败不可转换为 retryable provider error。

## Good / Base / Bad

Good：真实 native timeout，intent→admission→原生stop→失败outcome可在新process重读。
Base：测试 fake client 没有底层执行观察，仍保存调用意图/结果，但明确不是停止证据。
Bad：只有intent或已知admission而缺stop，重启后同一run再次调用；必须拒绝。

## 验证矩阵

七角色成功/失败、intent提前持久化、assessment恢复不重调intent、exact input/schema/timeout
漂移拒绝、start-only拒绝、native stop与请求绑定、fallback route完整性、写失败和原异常
保留、结果secret拒绝、历史consultation digest不变、新schema parity。

## 存量数据处置

旧f88知识超时无可信收据，不回填。已经通过公开平台批准的8ca恢复保持不变；当前活动
执行不热加载本任务。未来调用才产生新事实；新journal不会复活终态Task或替用户批准。
