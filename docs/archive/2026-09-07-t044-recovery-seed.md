# T044 C2 — 新 Coder worktree 接续基础

本阶段由 Astra 实现平台功能，不是平台交付目录需求；T044 仍未完成。

## 成果与边界

- 新增 `GitWorktreeManager.seed_changes`：校验原捕获、双方权限、新 Task 身份、干净目标及基线祖先关系。
- 在临时 Git index 中三方预检；冲突拒绝且不改目标文件/index。成功后应用到新 worktree，返回新捕获。
- 不修改旧 Coder、历史 Task/审批，不提交候选，不生成 QA/Review，不调用真实模型。
- 应用后中断保留现场；未新增生产 CLI、dispatch、seed receipt 或 provider dirty admission。

## Bug Analysis: three-way preflight

### 1. Root Cause Category
E — Implicit Assumption：误以为 `git apply --check --3way` 成功意味着真正三方合并无冲突。

### 2. Why Fixes Failed
初版仅检查 exit code，真实冲突测试发现正式 apply 仍写入冲突文件和 unmerged index。

### 3. Prevention Mechanisms
P0：实际三方预检隔离到临时 index，冲突失败断言目标文件/index 字节不变；已实现。

### 4. Systematic Expansion
预检不是锁。正式写入前复核 source/target/config，写入后故障保留新现场；
调用方仍需排除并发写者。没有把“检查成功”扩展成 candidate 或人工授权。

### 5. Knowledge Capture
已更新 `.trellis/spec/core/delivery-recovery.md`、Git 文档和任务设计。
本仓无 spec template 镜像，不生成额外模板。

## 验证

全量867 passed /198.85s；最终增加属性规则防护及导出异常后，定向18 passed /72.42s。
Ruff/format488files、Mypy270files、offline lock/build、diff-check通过。模型调用0。
测试使用临时Git和专用MySQL测试库；没有写入真实需求数据库或应用真实Coder补丁。

## 后续工作

新基线规范复核、批准内容显式继承、人工恢复入口、新 Task/dispatch/seed receipt 与真实
Coder→QA→Reviewer 尚需连接。回滚为撤销本阶段源码提交，无数据库或业务记录迁移。
