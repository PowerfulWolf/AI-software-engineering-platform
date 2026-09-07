# T044 — 显式恢复执行入口

日期：2026-09-07。源码父基线 `581432e`；实现位于本记录所在提交。

## 范围与成果

- 恢复分配进入原 MySQL 全局资源锁，重算 Scheduler/ModelRouter，三名独立 Agent 串行执行。
- 原生 Planner dispatch 与 recovery dispatch 保持不同类型；不伪造新 Planner 或覆盖旧请求。
- `ase recovery propose / inspect / approve / run`，精确计划批准、不可变 seed/invocation 记录。
- 恢复 Coder 只接受 exact seed；正常任务的干净工作树前置条件保持不变。
- 复用现有 Runtime 和候选/QA/Review 校验；原联合需求上下文继续进入新 Context。
- 新恢复 Task 的评估事件保留，但不重复计入 fresh-demand ADR；原失败保持原样。

## 验证

首个单仓真实 Git/MySQL、模拟 Codex 子进程的完整恢复测试通过：73.65 秒，Coder→QA→Reviewer
产生四份制品并进入 DONE，原 Coder、旧终态和逻辑项目保持不变。该结果仅为离线平台测试，
不是实际目录需求的交付。完整回归和最终结果见本任务 implement.md。

最终全量 **884 passed /292.03s**（包括联合子仓恢复），最终只读进度/CLI/记录 **4 passed
/71.77s**，Runtime/Codex/CLI 回归 **36 passed /1.60s**。Ruff/format505files、Mypy284files、
offline lock/build、diff-check 全部通过。平台开发测试期间真实模型调用为 0。

## 排查与沉淀

1. 测试环境等待：首次测试的退出卡在 pytest 旧临时 Git 树清理；改用新的 mktemp basetemp，
   不删除广泛用户目录。之后堆栈显示实际耗时来自多轮 Git 当前事实复核，而非模型或死锁。
2. 历史读取：普通 project status 会 reconcile 当前 preparation，不能用它验证换基线前的
   历史 checkpoint；恢复测试改为原生只读事实校验，不放宽旧入口的漂移守卫。
3. 上下文跨层：ContextBundle 的 source 名带 `source:` 前缀，恢复路由需还原 source_id，
   增加联合子仓 fixture，防止只通过单仓测试后遗漏 parent-approved context。

分类是跨层契约、隐式假设和测试覆盖缺口；具体防线已记录到 delivery-recovery spec。
没有新增通用 DAG、消息队列、向量库或新状态机。

## 边界与回滚

只有一条显式 Codex route；provider 获准后结果不明时拒绝自动重跑。缺 seed receipt 的 dirty
目标保留并拒绝盲目重放。只交付新的 Task 分支/candidate/制品，不复活原父/子终态，不自动
完成多仓联合验收、不 merge/push/deploy。真实目录需求仍需 exact plan 批准后实际模型验证。

使用前可回滚本平台提交；写入 recovery_dispatch 后需保留支持该 kind 的 MySQL reader，
不能在保留这些分配时退回不识别它们的旧调度版本。无 SQL DDL 迁移或历史数据改写。
