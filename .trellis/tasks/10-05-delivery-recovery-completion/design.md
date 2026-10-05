# 交付恢复完整重构契约

## 已批准目标

执行 2026-10-04 产品交付方案的全部目标。分批实现只作为内部开发顺序，不能把首批修复称为整体完成。保留串行 Task、独立 Coder/QA/Review、真实 claim、冻结 ProductSpec 与不可变审计。生产业务交付保持暂停，两条已删除 K1 不复活。

## 生产流与接口

1. 可信本机 composition 提供 `LocalOperatorPrincipal`，Product 服务边界检查 PRODUCT，工程决定检查 ENGINEERING；请求/模型文本不能设置主体权限。新 Dispatch 的 preview 与 commit 使用同一 `EngineeringPolicy`，Task 冻结 exact Team/Project/Repository/root、版本、能力和有界额度。旧 Task 的 None 不追补。
2. Planner command/context/ExecutionPlan/PlanArtifact 传递可信 `PlanExecutionWindow`。每个 Coder `AgentRequest.work_slice` 绑定当前 reservation、完整步骤分区、原 Plan digest、source、window。预算决定可执行聚合步骤，保留至多一轮返工；并非每个 step 必须单独调用。原生/Responses adapter 在 CandidateCommitSkill 前检查输出，Orchestrator 封存读回后再检查；部分 slice 只能发布 progress。
3. 验证前提使用 `PlannedVerificationRequirement`，command 与 typed inspection 互斥。新增文件必须显式计划且 policy 可写；已存在文件来自 exact Git tree。命令必须是受控的增量验证入口。受控 executor registry 的发现与 candidate provider 使用同一真实注册，不能只看二进制或模型声明。实施前 receipt 不是测试 PASS；QA/Review 对最终 candidate 重新绑定并产出独立 verdict。
4. `AgentInvocationControl.prepare(request) -> AgentRequest` 在真实 role claim 内封存 invocation start。`completed(request,result)` 保存同一请求的确定性结果。重启重领只能重放原 Run/Context 的封存结果；start 无 result 的未知窗口禁止重复调用或退款，进入工程调查等待。新的真正调用使用新预算/Run/Context/claim。
5. `decide_delivery_disposition(DeliveryFailureFacts)` 是确定性责任/下一步解释，不是权限来源。owner-fenced `WorkerLease.wait_for_delivery` 持久化 exact disposition、保留 Task checkpoint、释放 lease。普通重试和 QA/Review 返工继续复用原 retry 引擎。真正越权、终局预算耗尽才终止。
6. `DeliveryWaitService.inspect(InspectDeliveryWait)` 从受控 store/工作区/进程事实产生 `DeliveryWaitInvestigation`；`resolve(ResolveDeliveryWait)` 只接受对应 proof digest，先封存真实工程主体决定，再调用 `MySqlRoleQueue.resolve_wait(resolution)`。队列事务重读 Task/Step/等待摘要及 live claim；已封存结果重放不调用模型，已停机 checkpoint 新调用精确消费原冻结额度。前提等待只有可信 preflight-before-invocation 事实与重检 READY 才能恢复未调用身份。缺停机证明保持明确工程调查，不接受用户 bool 或 lease 过期代替证明。
7. 目标源码更新与平台部署分离。目标基线更新需 append-only binding/新执行输入，原 Task.base_ref/Product/Plan/事件/批准不改写；同一个 Coder branch/worktree 继续，候选变更后独立 QA/Review 重验。完整保留中断草稿与冲突输入，不能用 successor 分支名称不断叠加。平台升级本身不改变源码 SHA。
8. read projection 从同一 durable disposition/receipt/queue/resolution 生成状态与历史。阶段、模型调用、心跳、等待责任、next action 是不同字段；等待不宣称工程或模型正在处理。v2 所有 receipt/admission、原 QA/Review finding、Coder 输入与每轮输出完整展示，技术证据可折叠。

## 验证矩阵

| 情况 | 必须证明的行为 |
| --- | --- |
| 正常完整候选 | 独立 QA/Review 对同 SHA，完整 artifact 链后 DONE |
| local timeout / provider 临时故障，合法草稿 | 同 Task/branch，完整 capture，新身份与有界预算，多轮不覆盖 |
| 删除/改名/0644↔0755 | regular UTF-8 完整前后 body 与 patch，可重启验证；binary/symlink/secret/deny 拒绝 |
| QA FAIL / Review REJECT 后中断 | 原 finding/evidence/位置与 supersedes 保留，current source/slice精确 |
| 已封存结果后崩溃 | 原 Run/Context 结果重放，零重复模型调用 |
| 已开始、结果未知/无停机证明 | 非终态工程等待，释放租约，无退款/重复调用；调查公开入口明确缺证据 |
| 实施前工具/镜像/验证入口缺失 | Coder未调用，可信 preflight证据；前提满足后原交付恢复 |
| 自由 inline命令/pytest全量目录/错误capability | preflight拒绝，不因前提READY扩大权限 |
| 平台升级与源码基线更新 | 两种事实独立；新输入有绑定，旧批准不改写，原分支保留 |
| 旧policy/terminal记录 | 不追加新权力、不重开终态，兼容恢复仍保留独立验收 |
| 待处理操作重启/重复提交/事实漂移 | 同digest幂等，不同digest拒绝，无部分队列/预算更新 |
| 两个K1及其他DONE | 不触发生产模型、不复活删除、不修改完成结果 |

## 回滚与存量

### 队列执行基线消费

`consume_baseline(queue, plan, binding, cursor=held_cursor)` 在原 Task process lock、queue authority和Task row fence内发布Git completion；文件binding和MySQL消费分开幂等。新增 `work_queue_execution_baselines` 按binding SHA封存exact plan/binding/前一有效step摘要/next WorkItem。
未调用的原item保持attempt/checkpoint，append-only source overlay并递增dispatch generation；已调用依据原typed reservation建立新attempt/item，消费相应工作或provider额度，无退款。`original_step` 保原文，`step` 读最新有效source，`step_for_invocation(item, baselineSHA)`读当时历史source；原CLAIMED/start不追溯变化。
有效QA环境FAIL使用REVERIFY_CANDIDATE，不重放旧FAIL；可信验证prepare的FINISHED工程失败使用RETRY_VERIFIER_PREPARATION，不伪造provider故障。两者重新领取独立QA/Review并消费冻结工作额度；NOT_STARTED仅恢复未用模型身份，UNCERTAIN保留等待。

本轮不直接生产改库。既有 K1 删除已通过正式 Operation 完成，审计与 sidecar仍保留。新 optional 字段在 None 时排除，旧 hash和wire保持；新增事实只在新授权/调用产生。部署前仅跑受影响增量与公开入口组合，空闲部署后做只读健康/列表校验。回滚前保留新模型/receipt读能力，不能用旧代码丢弃已持久化的新事实。
