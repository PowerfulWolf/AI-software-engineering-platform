# Agent 工作可视化设计（后续里程碑）

## 目标

可视化不是把 Agent 的聊天窗口搬到网页上，而是把一次交付变成可重放的事实视图：人类能
看到当前状态、哪个角色在运行、它读取了哪些 Context、产生了哪些 Artifact/Evidence、消耗了
多少预算、为什么重试或阻塞，以及下一步需要谁作决定。

目标项目的代码目录和外置 AI workspace 分工如下：

```text
目标项目（实际 cwd）                 外置 AI workspace（可视化事实源）
代码 / 测试 / 构建配置                 StateEvent / AgentRunEvent
项目原生规范与文档                    Context manifest / ProjectProfile
Git refs / candidate commit           Artifact / Evidence / Handoff
                                     Evaluation / logs / conflict resolution
```

UI 不扫描模型隐式会话，也不把 Agent 自由文本当成状态事实。所有展示都从 sidecar 中的 typed
记录和目标项目的只读 Git inspection 生成。

## v0.1 后的最小视图

### 1. Task board

按 `NEW → PLANNING → IMPLEMENTING → QA → REVIEW → DONE/BLOCKED/FAILED` 展示任务卡片。卡片
显示当前 attempt、candidate SHA、最后一个事件、等待的角色和人工动作；状态颜色来自
`StateEvent`，不是 Agent 文本。

### 2. Run timeline

以时间线串起 `CaseStartedEvent → AgentRunEvent → StateEvent → Artifact/Evidence`。每个节点都
显示 `run_id`、role、context manifest ID、spec/policy 版本、输入 Artifact IDs、输出 digest、
耗时、token budget 和失败分类；点击可跳到 immutable JSON 或脱敏日志。

### 3. Agent detail

按 Coder/QA/Reviewer 展示权限、有效 cwd、读取/写入路径、命令、candidate SHA 和 verdict。
权限是机器 policy 的投影，UI 不提供扩大权限的编辑入口。

### 4. Human inbox

聚合 `SPEC_CONFLICT`、`POLICY_VIOLATION`、预算耗尽、非法输出和需要手工合并的 Handoff。
每项必须给出冲突双方的规则版本、Evidence、建议处理方式和“更新平台规范 / 更新项目规范 /
修正任务”的明确选项；解决结果写入 `HumanActionEvent`，不能只停留在 UI。

## 数据与接口路线

1. T021 起所有命令输出、diff、测试、模型调用和状态变化都写为可定位的 Evidence/Events；
2. T024 建立只读 `RunProjection` 与本地 JSON/HTTP read API，从 SQLite Task/Event、
   ArtifactStore、EvaluationEventStore 和 sidecar manifest 重算，支持按 project/task/run/role/
   candidate 查询，默认脱敏并分页；API 不执行 Agent、不迁移状态、不接受 verdict 写入；
3. T025 实现本地 dashboard（Task board、timeline、Agent detail、human inbox），先消费 read API，
   再考虑实时 SSE/WebSocket；实时推送只传递新增事件 ID，客户端可从 durable store 重放；
4. 后续才评估跨项目聚合、长期指标、告警和权限分级。没有测量数据前不引入消息队列、向量库
   或分布式 tracing 平台。

## 必须保留的安全边界

- Agent 输出和仓库内容在 UI 中标记为不可信数据，不能覆盖 policy 或触发按钮动作；
- 所有链接带 source revision、context/artifact digest 和 evidence URI，缺失时显示“不可验证”；
- secret redaction 在写入 sidecar 前完成，UI 不能请求原始 provider body；
- projection 是纯读模型，任何状态迁移、冲突解决和 merge 仍由 Orchestrator 或人工边界完成；
- UI 断线、重复消费或重放不会改变 Task、Artifact 或 verdict。
