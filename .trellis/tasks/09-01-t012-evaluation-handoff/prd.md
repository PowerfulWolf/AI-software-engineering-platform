# T012 — Evaluation metrics, ADR, and human handoff

## Goal

让 v0.1 能从持久化事实重算交付质量，而不是信任一次性汇总数字；同时为 `DONE` 和
`BLOCKED` Task 生成无需阅读内部日志即可处理的自包含交付包。

## Scope

- 新增不可变 Evaluation event contract，记录 case 启动、Agent run、人工动作和回归观察；
- 通过 `EvaluationTraceBuilder` 从 TaskRepository、ArtifactStore 和 EvaluationEventStore
  组装可重放 trace；
- 通过纯 `EvaluationEngine` 计算 completion、first-pass、artifact validity、evidence
  coverage、cycle time、attempt、regression、escalation、policy violation 和 ADR；
- ADR 使用 `ELIGIBLE / INELIGIBLE / PENDING`，缺失观察窗口不能静默算成功；
- 为终态 Task 构造 typed `HandoffBundle`，包含 candidate、验收证据、事件、制品、风险、
  阻塞原因和人类下一步；
- 评估事件与交付包采用 immutable canonical JSON、原子写入和 exact replay；交付包同时输出
  可读 Markdown。

## Non-goals

- 不修改串行 Coder → QA → Reviewer 状态机，不引入 DAG、并行 Agent、队列或向量库；
- 不自动 merge、部署或把人工动作推断为未发生；
- 不新增 PostgreSQL/observability 平台；v0.1 使用文件端口，未来可替换实现；
- 不把 metrics 汇总当作事实来源，汇总必须能由 trace 重算。

## Acceptance Criteria

- [ ] 相同 trace 重算得到完全相同的 case assessment 和 summary；
- [ ] `DONE` + 独立有效 QA/Review + 完整 evidence + 无不合格人工/策略动作 + 回归窗口通过
  才能计入 ADR；
- [ ] `DONE` 但未完成回归观察时 ADR 为 `PENDING`，仍进入分母但不进入分子；
- [ ] 首次 QA/Review、artifact validity、evidence coverage、attempt 和 cycle time 从事实计算；
- [ ] Evaluation event exact replay 幂等，冲突 ID、损坏文件和跨 case/task 事件 fail closed；
- [ ] `DONE` handoff 展示四制品链、candidate、验收证据、changed files、风险和复核命令；
- [ ] `BLOCKED` handoff 展示分类、原因、最后 evidence 和安全的人类下一步；
- [ ] Handoff exact replay 幂等，冲突或篡改拒绝；JSON 与 Markdown 同步落盘；
- [ ] 至少 5 个合成 cases 覆盖 eligible、pending、human intervention、blocked、regression；
- [ ] Ruff、format、strict mypy、pytest、lock/build 和 diff check 全部通过。

## Validation Matrix

| 输入 | 结果 |
|---|---|
| 完整自治 DONE + 回归 PASS | `ADR=ELIGIBLE` |
| DONE 缺回归观察 | `ADR=PENDING`，不计入分子 |
| DONE 有改码/改测试/改 verdict/放宽 policy | `ADR=INELIGIBLE` |
| QA/Review 非独立、revision/lineage/evidence 不完整 | `ADR=INELIGIBLE` |
| BLOCKED/FAILED/非终态 | completion/ADR 不成功，保留分类 |
| event ID exact replay | 幂等返回原事件 |
| event ID 不同正文、损坏 JSON、身份不一致 | typed error，旧事实不变 |
| 非 DONE/BLOCKED Task 请求 handoff | typed `HandoffNotReady` |
| DONE 缺四制品链 | typed `HandoffContractError` |

## Rollback

删除 `evaluation/`、对应 tests/docs/schema 即可回退；既有 Task、StateEvent、Artifact、
Orchestrator 与 SQLite 数据不变。
