# 分支与交付状态核验（2026-10-12）

远端现仅有 `main`。实际清理20个远端非main分支；与最初19个的口径不同，期间新增过维护分支。原始清单不改写，本记录保存核验后的结果。
所有以下精确分支头都已验证是 main 的祖先；补丁等价的历史实现先经独立核验再补齐祖先关系，未用旧实现覆盖主干增强。

| 已整合并删除的远端分支 | 原分支头 | 内容 |
| --- | --- | --- |
| `ai/task_t001_python_cli/attempt-1` | `4b790259` | feat: bootstrap Python CLI |
| `ai/task_t002_domain_models/attempt-1` | `fc1fd775` | feat: add typed domain contracts |
| `ai/task_t003_sqlite_repository/attempt-1` | `2e7ed76a` | feat: add sqlite task repository |
| `ai/task_t004_state_machine/attempt-1` | `e6c869fc` | feat: add task state machine reducer |
| `ai/task_t005_artifact_store/attempt-1` | `b08ab8cf` | feat: add immutable artifact store |
| `ai/task_t006_git_worktree/attempt-1` | `bd52bc4e` | feat: add isolated git worktree manager |
| `ai/task_t007_context/attempt-1` | `402c49fd` | feat: add deterministic context builder |
| `ai/task_t008_fake_agent/attempt-1` | `7143b467` | feat: add deterministic fake agent adapter |
| `ai/task_t009_orchestrator/attempt-1` | `3ea3523b` | feat: add serial orchestrator happy path |
| `ai/task_t010_retry/attempt-1` | `4f3ed833` | feat: add bounded retry and recovery orchestration |
| `ai/task_t011_real_agent/attempt-1` | `52ee8284` | feat: add real agent adapter and context store |
| `ai/task_t012_evaluation_handoff/attempt-1` | `e2ecaf41` | feat: add replayable evaluation and handoff |
| `ai/task_t013_cli_runtime/attempt-1` | `601ffb3b` | feat: add offline cli runtime commands |
| `codex/baseline-read-performance-20261011` | `b812c4d0` | perf(read): reuse the validated plan within a complete baseline read |
| `codex/maintenance-completion-20261012` | `daa96b7c` | feat(console): add controlled maintenance completion and normal-mode admission |
| `codex/native-output-bounds-20261011` | `fba82f3a` | fix(runtime): bound native process output while execution is running |
| `codex/t046-worker-integration-20260919` | `9c214313` | add trellis |
| `codex/team-read-performance-20261011` | `fa8ffee1` | fix(console): bound repeated history reads and back off slow polling |
| `task/capacity-receipt` | `bdab7bf1` | docs(delivery): retain failed production knowledge scope proposal |
| `task/delivery-input-recovery-integration` | `770c02e8` | docs(delivery): record first preserved K1 Coder claim and invocation |

本地累计删除94个已合入的非main分支。49个历史工作区（包括2项缺失目录注册）已处理：存在的工作区在原HEAD转为detached，逐项核验Git文件状态不变；仅清理缺失目录的Git注册。工作区目录、未提交/未跟踪文件和已有stash均保留。分支名删除不删除已由main保留的提交。

## 唯一未合入分支

`task/offline-native-recovery-fixtures`，头 `c210c22`，另有 `tests/recovery/test_execution.py` 未提交调试修改。分支包含真实离线子进程、失租约与历史恢复回归夹具，以及仍处设计阶段的队列等待解释。相对main没有生产代码或Schema修改。
最近完整的三个精确节点仍为3 failed。后续单例probe已观察真实DISPATCHED和EXECUTION_UNCERTAIN，不能再把所有Pending概括为没有派发；联合child的Task仍为IMPLEMENTING，终态reader拒绝。调试修改未完成验收，未合并、未删除、未宣称通过。

## 当前服务与K1

服务已为normal，delivery_ready=true，创建/审批/继续交付入口可用。当前摘要GET 200、约3.39秒；完整详情首次503，复查200但耗时约13.79秒。入口可用不等于前端读取性能已完全验收。
K1原Task检查点IMPLEMENTING、执行状态WAITING、WorkItem WAITING_DEPENDENCY，原因ENVIRONMENT_UNAVAILABLE：实施前注册验证能力所需工具/环境未满足。没有正在执行Coder的证据，K1尚未完成QA/Review完整交付。本次只读核验，没有继续或审批K1。

## 验证、存量数据与回滚

仅Git祖先/分支/远端核验、JSON解析、git diff --check和公开只读API；本轮没有修改生产代码，无需运行全量或额外测试。未改生产Task、审批、队列、verdict或开发草稿。
历史分支精确SHA保留在JSON；需要恢复分支时可从该SHA重新建立分支。未合入夹具现场保留。平台完整交付能力仍需该回归分支收尾和真实K1独立QA/Review验证，不能只凭delivery_ready宣称验收完成。
