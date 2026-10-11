# 完整基线读取消除重复计划解析

## 目标

一次完整 `bindings_for_task` 对每个 binding 已读取并校验 plan、start 和 authority，随后调用 `required_context` 再次读取 plan 并构造丢弃的大段 Context。提取仅在同一次调用内接收已校验 typed plan 的私有补丁检查；保持公开 Context 入口独立 fresh 读盘。

## 范围

- 不缓存跨请求事实，不截断历史或补丁，不改变 Schema、审批、队列、Task 与 native rule 验证。
- 每个完整 binding 的 baseline-plans 读取从两次减少到一次；start、authority 和 native rule 仍按原路径完整检查。
- 公开 `required_context(binding)` 的返回文本逐字不变，仍检查 binding integrity 并读取完整 plan。
- 仅在隔离 worktree 实现；生产活跃时不部署。

## 验收

- [x] 真实 Git/baseline fixture 先红后绿，统计实际 store 读取而非仅测试 helper。
- [x] 完整 Context 文本与先前契约一致，公开入口每次独立读盘。
- [x] URI/hash/bytes、Task、input mode 与后来 plan 篡改反例拒绝；完整 start/authority/前驱/epoch 回归通过。独立 review 核验 purpose 保持检查并新增精确 plan identity 检查。
- [x] 增量测试、scoped Ruff/mypy、独立 review 通过。

## 存量数据与回滚

无存量迁移，不写生产事实、不更新现有 Task 基线。空闲后受控加载代码即可；回滚只恢复重复读取成本。读取工作量改善不等于已证实完整页面延迟改善。
