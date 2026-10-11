# 负向凭证测试的动态 fixture 指导

## 目标

让可写源码的 Coder/QA 在生成负向 credential/fence-token 测试之前收到统一 machine
guidance：从独立、获当前权限允许的 fixture 获取动态生成的 token/reference，保持非空且未知
的 token 与合法 fixture token 分离，保留原负向测试意图与已有非空未知/空值/过期断言
（适用时），避免固定疑似凭证字面量阻断完整 capture；不增加新的过期验收要求。

## 范围

- 只改 `RequestPromptBuilder`、`ContextPromptBuilder` 的共用机器指导及真实 builder 回归。
- native 消费同一 PromptPayload，不复制 native guidance 或增加服务。
- 不改 scanner、Schema、状态机、权限或恢复审批，不读取/修改 K1，不操作生产、DB、API 或模型。
- 独立 worktree `ase-negative-token-guidance`；base `38ae78f`。

## 验收

- [x] 两个真实 builder 的 writable Coder/QA 测试先红后绿。
- [x] 指导只出现在 system 消息；只读 Coder/QA、Reviewer、Orchestrator 不获得源码修改指导。
- [x] 指导要求独立动态 fixture/reference、保留原意图与已有适用的非空未知/空值/过期断言，禁止固定字面量、
  编码/拼接逃避扫描、削弱测试和放宽 policy；无法合法构造时明确报告 blocked。
- [x] 两个 builder 引用一处 guidance；机器 permissions 与 output contract 保持。
- [x] focused pytest、scoped Ruff/mypy 与 diff check 通过；提交供 root 独立 review，不自行 merge。

## 存量数据处置与回滚

本变更只影响之后构造的 prompt，不修改现有冻结 Context、Task、Operation、审批或历史事实。
现有受 capture 拒绝的源码仍须按已授权、带人工审计的维护流程修复，重新完整核验，再由公开精确
恢复入口继续；本指导本身不授权修复或继续。回滚本次 prompt、测试与文档改动即可。
