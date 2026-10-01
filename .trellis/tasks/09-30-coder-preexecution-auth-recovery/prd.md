# Coder 续跑知识失败的精确恢复

## 已核实的问题

最新 Task `task_recovery_7bf274ef749e81bb78aa504df594278c` 已在 attempt 1 执行真实 Coder，
接受 `coder-progress` 后保留 8 文件改动。attempt 2 在知识准备失败，未执行新的 Coder。
旧恢复发现器要求 route/context attempt 等于 Task 最新 attempt，因此无法发现合法来源。
CLI 在本地 watchdog 到期时扫描完整人类可读 transcript，把项目文本的 login/authentication/401
误当成 provider 认证错误；最小回归可稳定复现（真实该次没有完整诊断，不能断言真实认证已排除）。

## 范围

- 仅接纳严格证实的四事件尾部：progress 接纳 → QUEUED → 下一 attempt IMPLEMENTING → 知识失败。
- 保留真实旧 run/context/attempt；验证 sealed artifact、无后续 route/活跃 claim、worktree HEAD 与 dirty paths。
- 经普通 recovery plan 精确批准复制当前完整改动，独立 Coder → QA → Reviewer。
- structured Codex CLI 使用 JSON 事件，仅顶层 error/turn.failed 与 stderr 显式诊断用于分类；忽略模型/工具正文。
- 不生成新的 retry lineage 计划；保留历史 retry lineage 的只读 Schema 兼容，不重置旧 Task，不修改历史事实，不放宽认证错误 fallback。

## 验收

1. 正常发现该生产 Task 的真实 attempt 1 身份，保留全部 8 文件。
2. 错误事件、进度/工作树漂移、后续 route、活跃执行、旧审批拒绝。
3. 离线真实 Git/MySQL 完成恢复 Coder → QA → Review，旧 Task/事件不变。
4. 本地 timeout 与 provider 401/403/429/504 保持正确分类，普通 transcript 不影响分类。
5. 仅增量测试、Ruff、相关 Mypy；生产通过 Console 精确审批继续交付。

## 允许路径与回滚

`src/ai_software_engineer/agents/structured.py`、`recovery/{native,progress_source}.py`、相应 tests，
`.trellis/spec/core/{delivery-recovery,execution-retry-policy}.md` 与本任务目录。
回滚只撤销这组平台代码并重启 Console；所有生产 Task/Artifact/Worktree 保留。
