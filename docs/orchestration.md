# Orchestrator 核心流程

## 1. 责任边界

TaskOrchestrator 是一个 Task 交付状态的唯一写入者。它不实现业务代码，也不根据模型自然语言
推断“应该算通过”；所有决定依赖可校验 Artifact、Git 元数据和显式策略。

PortfolioScheduler 位于它上层，管理 WorkQueue、Agent capacity、RoleAssignment、TaskLease 和
ModelSelection。Scheduler 不写 TaskStatus、不解释 verdict；TaskOrchestrator 不拥有全局 Agent
或决定队列优先级。这两个独立 seam 避免把跨 Task 调度复杂度塞进交付状态机。

```text
WorkQueue
  → PortfolioScheduler.match(WorkItem, AgentProfile)
  → RoleAssignment + TaskLease
  → ModelRouter.select(...) → ModelSelection
  → AgentRunAllocation
  → TaskOrchestrator.run_task(task_id)
```

当前代码只实现最后一层串行 TaskOrchestrator；T019 实现前面的 Scheduler/ModelRouter。

## 2. 核心流程

```text
接收 Task
  ↓ validate + persist
生成 plan（可由规划 Agent 或受限 Coder 规划模式完成）
  ↓ schema/evidence 校验
创建 Coder worktree → 启动 Coder
  ↓ implementation-report + candidate commit
创建 QA worktree → 启动 QA
  ├─ FAIL → 分类 finding → retry Coder 或 BLOCKED
  └─ PASS
       ↓
创建 Reviewer worktree → 启动 Reviewer
  ├─ REJECT → 分类 finding → retry Coder 或 BLOCKED
  └─ APPROVE → DONE（输出交付包）
```

## 3. 伪代码

```python
def run_task(task_id: str) -> DeliveryResult:
    task = store.load_task(task_id)
    assert transition(task, "PLANNING")

    # v0.1 不新增 Planner 角色：由 Orchestrator 以 planning mode 调用 adapter，
    # 产出 plan artifact，但不获得业务代码写权限。
    plan = run_agent(role="orchestrator", mode="planning", task=task)
    validate_artifact(plan, kind=ArtifactKind.PLAN)
    store.put(plan)

    while task.attempts < task.max_attempts:
        task.attempts += 1
        assert transition(task, "IMPLEMENTING")
        ctx = context.build(task, role="coder", attempt=task.attempts)
        coder_result = agents.run("coder", ctx, policy=policy.for_role("coder"))
        impl = validate_and_store(coder_result, "implementation-report", task)
        if not impl.valid or not git.is_allowed_candidate(impl.commit_sha, task):
            return block(task, "invalid_coder_output")

        assert transition(task, "QA")
        qa_ctx = context.build(task, role="qa", candidate=impl.commit_sha)
        qa_result = agents.run("qa", qa_ctx, policy=policy.for_role("qa"))
        qa = validate_and_store(qa_result, "qa-report", task)
        if qa.status == "FAIL":
            decision = route_failure("qa", qa, task)
            if decision == "retry":
                continue
            return block(task, decision.reason)

        assert transition(task, "REVIEW")
        review_ctx = context.build(task, role="reviewer", candidate=impl.commit_sha)
        review_result = agents.run("reviewer", review_ctx, policy=policy.for_role("reviewer"))
        review = validate_and_store(review_result, "review-report", task)
        if review.verdict == "APPROVE":
            assert git.clean_candidate(impl.commit_sha)
            assert transition(task, "DONE", artifacts=[plan, impl, qa, review])
            return deliver(task, candidate=impl.commit_sha)

        decision = route_failure("review", review, task)
        if decision == "retry":
            continue
        return block(task, decision.reason)

    return block(task, "attempt_budget_exhausted")
```

上面描述 M3 完整目标；T009 已实现单 attempt happy path，T010 通过同一组端口增加了
`RetryingOrchestrator.run_task(task_id) -> DeliveryResult | BlockedResult`。它从 durable
Task/event/Artifact checkpoint 恢复，不重复已读回的有效 Artifact。

```python
SerialOrchestrator.run_task(task_id: TaskId) -> DeliveryResult
```

T009 严格只接受 `NEW` Task，不包含 retry loop；T010 接受 `NEW`、`PLANNING`、`IMPLEMENTING`、
`QA`、`REVIEW` checkpoint，并按最多 `Task.max_attempts` 次尝试执行。旧 Artifact 永不覆盖，
修复后的 implementation-report 通过 `supersedes` 和 QA/Review finding parent 建立 lineage。

每次 run 的执行顺序固定为：

```text
读取当前 durable Task 快照
  → FileRunContextBuilder(机器 policy + Task + role + ArtifactStore 上游 Artifact)
  → AgentRequest → AgentAdapter
  → request/result 与跨对象 gate 校验
  → seal_artifact → ArtifactStore.put/get
  → build_event → TaskRepository.append_event → 重新读取 Task
```

只有 ArtifactStore 读回的 Artifact 才进入下游 Context；不传递上游 Agent 隐式会话。

## 4. 运行不变量

- 每个 Agent run 必须有唯一 `run_id`、context manifest 和 timeout；
- Agent 超时/崩溃不产生 verdict，Orchestrator 记录 `interrupted` 并按重试策略处理；
- 同一 `run_id` 重放必须幂等，不能重复创建状态事件；
- artifact 校验失败不能被“降级接受”；
- `DONE` 必须引用完整的 plan、implementation、QA、Review lineage；implementation、QA、
  Review 必须使用同一 candidate revision，plan 可绑定 Task base revision。
- Coder request/context revision 是输入基线，implementation-report revision 是新 candidate 且
  必须等于 `content.commit_sha`；不能在 Coder 启动前虚构未知 candidate。
- plan/implementation/QA 对 Task criterion ID 必须精确全覆盖；4 个 producer run ID 必须独立。

- 每次 Agent attempt 先通过 `TaskRepository.record_attempt` 持久化；StateEvent 记录对应
  `attempt`，进程重启后以事件与快照中的最大 attempt 恢复预算。

## 5. T010 路由摘要

| 失败 | 动作 |
|---|---|
| timeout/provider error/invalid output | 在预算内重试当前 role；失败结果不产生 verdict |
| QA `FAIL` | 持久化 qa-report，带 findings 回流 Coder，创建新 candidate |
| Review `REJECT` | 持久化 review-report，带 findings 回流 Coder，创建新 candidate |
| 临时 provider/依赖不可用 | WorkItem → `RETRY_SCHEDULED/WAITING_DEPENDENCY`，释放 Lease |
| 需求不明确/规范冲突 | WorkItem → `WAITING_HUMAN`，释放 Lease，Task 保持 checkpoint |
| policy 终止/预算终局用尽 | 生成 `BlockedResult`，追加 Task `BLOCKED` event |
| 内部不变量破坏 | 保留现场并追加 `FAILED` event |

同一 attempt 的上下文只来自声明的已持久化 Artifact；重启恢复会扫描本 Task 的可信
Artifact，识别最新 plan/implementation/QA/Review，并从最近合法状态继续。

## 6. 交付包

`deliver()` 生成一个只读索引：Task、base_ref、candidate_sha、diff 路径、四类 artifact、测试命令/输出和未解决风险。交付包不执行 merge；人类或后续发布流程决定是否合并。
