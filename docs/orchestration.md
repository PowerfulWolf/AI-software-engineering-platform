# Orchestrator 核心流程

## 1. 责任边界

Orchestrator 是唯一的状态写入者和路由决策者。它不实现业务代码，也不根据模型自然语言自行推断“应该算通过”；所有决定都依赖可校验 artifact、Git 元数据和显式策略。

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
    validate_artifact(plan, kind="plan", source_revision=task.base_revision)
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

## 4. 运行不变量

- 每个 Agent run 必须有唯一 `run_id`、context manifest 和 timeout；
- Agent 超时/崩溃不产生 verdict，Orchestrator 记录 `interrupted` 并按重试策略处理；
- 同一 `run_id` 重放必须幂等，不能重复创建状态事件；
- artifact 校验失败不能被“降级接受”；
- `DONE` 必须引用同一 candidate revision 的 plan、implementation、QA、Review artifact。

## 5. 交付包

`deliver()` 生成一个只读索引：Task、base_ref、candidate_sha、diff 路径、四类 artifact、测试命令/输出和未解决风险。交付包不执行 merge；人类或后续发布流程决定是否合并。
