# 自我迭代阶梯

目标：让 ASE 真正交付对自身仓库的修改。原 K1（自动知识收集闭环）一次冻结了约 53 个路径，单个 Coder
窗口被分到 8 个步骤，1800 秒内无法完成，于是每次中断都需要专用恢复。新做法：需求从小到大，每一级
只有在上一级稳定 DONE 后才开始；每次失败都是一个真实的平台问题，修复后进入新的运行版本。

## 规则

- 每个需求的技术方案不超过 6 个实现步骤（默认容量：每次 Coder 最多 3 步 × 2 次工作，另留 1 次返工）。
  超过时 Planner 阶段会直接报“需求过大”，请拆分后重新提。
- 只用固定运行版本跑 ASE（见 [runtime-releases](../operations/runtime-releases.md)）。
- 失败时先记录：哪一阶段、哪种原因、是否需要人；修平台 → 发新版本 → 新建同一需求重试。不为单个需求写专用恢复路径。
- 每级 DONE 后人工合并候选分支，再决定是否发版。

## 阶梯

下面每条都可以直接作为 Console 中的需求原文。

### L0 冒烟：只改文档

> 在 `docs/operations/runtime-releases.md` 末尾增加“常见问题”一节，说明 `activate` 被拒绝（仍有执行未结束）时
> 应该等待并重试，而不是强杀进程。验收：该节存在且内容与 `ase-console-service.sh` 的行为一致；不修改其他文件。

验证整条链路：Product → Design → Plan → Coder → QA（文档检查）→ Reviewer → DONE。

### L1 小代码改动 + 单测

> 让每次 Coder 可执行的最大步骤数可配置：在 `ExecutionRetryPolicy` 中增加 `coder_max_steps_per_run`
> （1–16，默认 3），生产组装用它替代 `DEFAULT_CODER_STEPS_PER_RUN`。验收：默认行为不变；配置为 2 时新计划的
> 执行窗口记录 2；越界值被拒绝；同步 `schemas/production-config.schema.json`；`tests/planning` 和
> `tests/config` 通过。

### L2 用户可读的阻塞原因

> 当 Planner 因“需求过大”拒绝计划时，Console 需求详情显示中文原因与拆分建议，而不是通用失败文案。
> 验收：有对应 team_view 读模型/文案测试；其他 Planner 失败文案不变。

### L3 修复现有的 schema 生成脚本

> `scripts/sync-stopped-unknown-budget-schema.py` 与 `scripts/sync-owned-session-schemas.py` 在干净检出上运行失败。
> 修复或明确记录其前置条件，使全部 `scripts/sync-*.py` 在干净检出上可运行且不产生意外差异。
> 验收：新增测试在临时副本中运行全部生成脚本并断言无差异。

### L4–L9 自动知识收集闭环（原 K1 拆分）

每条对应 [backlog K1](backlog.md#k1) 的一项，按顺序做：

| 级 | 需求 | 验收要点 |
|---|---|---|
| L4 | 定义采集事件与稳定身份（Team/Project/Repository、Task/Run、角色、artifact ID/SHA、observation ID），只做模型与校验 | 模型、schema、正负例单测 |
| L5 | 报告接纳后登记可恢复的采集工作项，复用现有持久机制 | 接纳与登记之间中断后可对账补登记 |
| L6 | 有界批次、持久游标、幂等去重、失败原因与显式重试 | 重复触发/重启不产生重复提案 |
| L7 | 自动入口与显式 collect 共用提案身份和服务 | 显式与自动并存时提案唯一、不覆盖已有审批 |
| L8 | 失败隔离：采集失败不改 verdict、不阻塞报告、不自动发布 | 故障注入测试 |
| L9 | 开关与停用语义 + 旧数据有界补采 | 关闭后保留历史，显式入口仍可用 |

全部完成后，按 backlog 的完成标准做一次 A→B 端到端验收：需求 A 的报告自动形成待审提案，批准发布后需求 B 可检索并引用。

## 记录

每级完成或失败都在下表追加一行，作为 Planner 调整拆分粒度和 `DEFAULT_CODER_STEPS_PER_RUN` 的依据。

| 日期 | 级 | 结果 | 运行版本 | 失败阶段/原因 | 平台修复 |
|---|---|---|---|---|---|
