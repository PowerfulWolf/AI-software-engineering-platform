# 非临时执行故障分类与普通工作额度

## Scope / signatures

`orchestration.retry.RetryClassification.NONTRANSIENT_INFRA` 和
`domain.delivery_disposition.DeliveryFailureFacts.classification` 表示真实失败，但没有可信的
可自动重试临时故障事实。原 `AgentResult.error`、Run、stop、evidence 和 attempt 不改变。

`_classification(AgentRunFailed)` 与知识准备 `StructuredModelError` 的分类门仅在
`transient is True` 且 `code.value in TRANSIENT_CODES` 时选择 `TRANSIENT_INFRA`。
`INVALID_OUTPUT` / `POLICY_VIOLATION` 保留专用分类；知识本地时限保留专用及旧兼容路径。

## Contracts

- 非临时失败不追加 `DeliveryRetryFailure`，不退工作额度，不自动请求新模型。
- `WorkerDeliveryFailureControl.wait` 对新分类核验普通工作额度；剩余临时额度不是工作额度。
- 普通额度尚余：`INVESTIGATE_EXECUTION`、engineering responsibility，真实 Lease 释放，
  Task 保持最后交付 checkpoint；剩余额度本身不是继续授权。
- 普通额度耗尽：`TERMINATE` 后原编排追加 BLOCKED，保留所有失败和候选；不能无限工程等待。
- 已有 stopped-provider/completed-output 恢复可以识别新分类，仍必须验证各自精确 proof；
  不能由新分类推断 AUTH、完整输出、停止或可恢复。
- 只读 UI 使用中文解释真实失败；不把非临时故障解释成 provider outage 或预算退款。

## Validation matrix / test points

| 事实 | 预期 |
| --- | --- |
| 允许 code + transient=true | 原临时预算、新 attempt、新 claim 语义不变 |
| 允许 code + transient=false | NONTRANSIENT_INFRA、不退款、按普通工作额度 |
| AUTH / unknown / WORK_INTERRUPTED 无专用恢复事实 | 不伪装临时或已知凭证故障 |
| 非临时 + 尚余普通额度 | 工程调查 wait，释放真实 Lease，无后续角色调用 |
| 非临时 + 普通额度耗尽、临时额度尚余 | BLOCKED，不永久 WAITING_DEPENDENCY |
| 新分类 + 精确 AUTH / completed-output proof | 原专用恢复门仍可用，proof 不放宽 |
| Schema 生成 / 重复生成 | 所有嵌入事实接受新类，原手写 guards 不丢失 |

Good：可信 failure flags 决定分类，真实冻结额度决定终局。Base：旧结果和审计历史完整。
Bad：仅看 provider code、错误字符串、Lease 到期或服务重启就退款、推断停止或启动新模型。

## 存量数据处置 / rollback

不重写旧分类、error/transient、retry、stop、Task 或审批。旧等待需要独立的公开受控结案，再经
原 Requirement 的精确恢复授权继续；不能直接改库或新增重复需求。发布需与该结案能力一起验证。
回滚时保留已写入新分类的兼容读取；不删除审计或回退到无法解析新事实的旧 Schema。
