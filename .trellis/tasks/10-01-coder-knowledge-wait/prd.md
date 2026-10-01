# 恢复 Coder 知识等待

## 目标及复现

K1 recovery Task `task_recovery_66fbbc0a50aba8927d79156a6e66c81a` 保留 IMPLEMENTING，第四个 WorkItem 已释放 Lease 并 WAITING_HUMAN。KnowledgeGap 已封存，父需求仍 BLOCKED，读投影却把非终态 Task 当成运行中显示 DELIVERING。`resume_execution` 只接受 verifier gap，报 `recovery knowledge wait is not at a verifier checkpoint`。

## 范围和验收

- 允许修改 recovery/entry.py、resume.py、新 recovery knowledge wait helper、team_view/reader.py、app.js、对应测试、规范及本任务。
- 精确获批 recovery 的当前 Coder 知识等待优先于首次失租约恢复；不重跑模型、不改权限或预算。
- 以当前唯一未关闭 WorkItem、queue admission/step、Task revision、gap/route/context/manifest 和批准的 dispatch 验证归属；历史 gap 不作当前依据。
- 原生 child 接回父需求后走正常 WAITING_HUMAN journal 和知识批准 facade；批准后正常新 claim 继续串行角色。
- UI 在父 journal 接回前也不能把 WAITING_HUMAN 队列显示为正在执行；不把历史 Manager 文案变成新审批。
- 增量覆盖当前等待、历史/错绑定拒绝、首次执行与重启接管、精确批准后继续、页面投影；独立 QA/Review。

## 存量和回滚

无 SQL 修复。加载修复后经原生 Continue 接回现有 gap，再用正式知识解答/范围/验证入口处理前提；解答不冒充权限扩展。所有历史、progress、worktree 和预算保留。回滚仅还原本修复代码，保留新增 journal 和审计，不重放已消费审批。
