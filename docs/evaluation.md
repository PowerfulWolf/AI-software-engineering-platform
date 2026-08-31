# Evaluation 指标与 Autonomous Delivery Rate

## 1. 评估单位

一个 evaluation case = 一个固定 Task、固定 base revision、固定 acceptance criteria、固定测试入口。每次模型/策略变更都在同一 case 集合上回放，避免把需求变化误当成能力变化。

## 2. 核心指标

| 指标 | 定义 | v0.1 目标 |
|---|---|---:|
| Task Completion Rate | `DONE` cases / started cases | ≥ 70% |
| First-pass QA Rate | 首次 Coder 后 QA `PASS` 的 cases / cases | ≥ 50% |
| First-pass Review Rate | 首次 Review `APPROVE` 的 cases / cases | ≥ 40% |
| Artifact Validity Rate | 首次 Schema/完整性校验通过的 artifact / artifact 总数 | ≥ 98% |
| Evidence Coverage | 有定位 evidence 的 required checks / required checks | 100% |
| Median Cycle Time | 从 `PLANNING` 到 `DONE` 的中位时间 | 持续下降，先记录基线 |
| Mean Attempts | 每个 case 的 Coder attempt 平均数 | ≤ 2.0 |
| Regression Escape Rate | 交付后人工/隐藏测试发现的问题 / DONE cases | < 10% |
| Human Escalation Rate | 进入 `BLOCKED` 且需人类决定的 cases / started cases | < 25% |
| Policy Violation Rate | 被拒绝的越权动作 / agent runs | 0 个未捕获 |

## 3. Autonomous Delivery Rate（ADR）

### 定义

在给定 evaluation 集合和时间窗口内：

```text
ADR = 满足以下全部条件的 DONE Task 数 / 已启动且纳入评估的 Task 数
```

“满足全部条件”包括：

1. 从 `NEW` 到 `DONE` 无人修改业务代码、测试或 verdict；
2. 未绕过或人工放宽任何 policy、budget 或状态迁移守卫；
3. QA 和 Reviewer 均由独立 run 产出有效 artifact；
4. required acceptance criteria、测试和 evidence 完整；
5. candidate diff 可由人类按交付包复核并合并（v0.1 不要求平台自动 merge）；
6. 在规定的观察窗口内没有已知回归（若有隐藏测试，纳入窗口）。

人工仅做“开始任务”和“查看/合并交付包”不降低 ADR；人工澄清需求、修代码、重写 verdict、批准越权或替平台补齐 evidence 都算非自治，Task 只计入 Completion Rate，不计入 ADR。

### 记录字段

每个 case 记录 `task_id`、`model_id`、prompt/spec 版本、base/candidate SHA、attempt 数、人工事件、状态事件、artifact validity、隐藏测试结果和 ADR 布尔值。指标必须可从事件流重算，不能只保存一个汇总数字。

## 4. 质量门槛

- 任何未捕获的 policy violation 或 artifact 伪造都是发布阻断项；
- ADR 提升不能以降低 evidence coverage 或放宽 Review 标准为代价；
- 每次失败都要按分类统计，优先修复重复出现的 failure mode，再调模型参数。
