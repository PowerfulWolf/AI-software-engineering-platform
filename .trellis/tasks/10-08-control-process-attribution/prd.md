# 本机恢复调查的进程归属

目标：用户在已结束旧 Coder 后可以继续准备保留进度方案；保持平台维护会话和 ASE 服务在线不应造成全账户假阻塞。

## 范围与验收

- 原生平台 Coder 的真实入口为 `codex exec`。独立交互 `codex resume` 和协议/控制服务不能仅因名字包含 Codex 被算成旧开发执行。
- macOS 的 `Codex Framework`、`Codex Computer Use` 路径不是 Codex CLI。命令参数包含控制进程名称不能获得豁免。
- 明确空闲 shell 仅 cwd 在工作区不是执行事实；未知工具、孤儿 Python/Node 的 cwd 和实际打开工作区文件/目录仍阻塞。直接交互 Codex 的 cwd 若就在被救援的 Coder checkout，仍阻塞。
- 真正 `codex exec`、包装执行和派生工具不可借维护进程父子关系逃过检查；两次完整进程清单、原生 birth identity、权限、时限和限长拒绝保持。
- Console/Host 公开准备、工程确认和执行使用同一真实 scanner；不伪造历史停止、不退款、不修改 QA/Review。
- 不替用户操作需求、审批或启动 Coder，不 kill 维护会话，不清空现场。

## 允许路径

`src/ai_software_engineer/manager/legacy_local_execution.py`、对应 scanner/public rescue tests、本任务文档、`.trellis/spec/core/legacy-execution-rescue.md`、`.trellis/spec/core/index.md`、`.trellis/spec/guides/recovery-thinking.md`、`docs/user/legacy-execution-rescue.md`。

## 验证与回滚点

仅跑 scanner/containment/Console/Schema 增量测试以及公开本机恢复的两条 MySQL 场景；Ruff/format/strict mypy/diff check。全量测试留给用户。

回滚基线 `fd05841`。本次不引入新持久化结构和迁移；受控停服后回滚再启动。回滚会重新带来假阻塞，不能删除审批、历史或草稿消除它。
