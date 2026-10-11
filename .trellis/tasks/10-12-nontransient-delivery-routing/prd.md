# 非临时执行失败路由

## 目标与范围

永久提供方失败和未知原生退出不得被标为临时故障。交付执行和知识准备使用同一可信门：
`transient=true` 且 code 属于 `TRANSIENT_CODES` 才进入临时分类；原错误及停止事实保持不变。
新增 `NONTRANSIENT_INFRA` 分类，工作额度尚余时交工程调查，普通工作额度耗尽时结束本 Task。

## 验收标准

- Coder/QA/Reviewer 和知识准备的非临时/未知失败不退款、不自动启动新模型；原失败保持。
- 有普通工作额度时提交真实 owner-fenced engineering wait 并释放 Lease。
- 无普通工作额度时返回真实 BLOCKED，不因仍有 transient 额度永久等待。
- 临时故障原有新身份/新 claim 重试和独立 QA/Review 保持。
- 新分类在所有嵌入 Schema 可读，中文前端解释与已验证恢复证明门保持一致。
- 已有 AUTH stopped-provider 和 completed-output 专用恢复不因分类修正失效。
- 只运行明确的增量测试；存量等待的公开结案由 Root 独立实现，不直接改库或重建 Requirement。

## 数据流

`AgentResult/StructuredModelError → RetryClassification → DeliveryFailureFacts →
deterministic disposition → owner-fenced Worker wait 或 BLOCKED → Host/read-only UI`。
模型文字与分类都不构成停止、退款、审批或恢复授权。
