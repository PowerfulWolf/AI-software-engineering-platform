# 保留受控验证宿主前提的安全诊断原因

## 问题

`RegisteredNativePythonVerifier.discover` 将受控 Python/MySQL 宿主发现过程的所有 `OSError`/
`ValueError` 压成 `CONTROLLED_VERIFICATION_CAPABILITY_UNAVAILABLE`。一条 Plan 有多个验收项时，
用户只能看到重复的泛化阻塞，无法知道是平台、Codex、Docker、Unix socket、MySQL 镜像还是运行时依赖。

## 目标与边界

- 在 typed immutable preflight observation 中保存有限、稳定、中文可映射的 `detail_code`。
- 只保存安全分类，不保存 provider stderr、完整 argv、绝对路径、DSN、密码或环境变量。
- 保持旧 `native_wait_reason`、旧 receipt 可读；新字段可选，不改变既有批准和恢复权限。
- `DeliveryWaitInvestigation.next_action` 展示一个去重后的具体前提处理提示；READY、已有合法恢复决定和
  非环境类缺项的语义不变。
- 不自动安装、启动 Docker、创建数据库、修改 Task/queue 或把能力缺失变成 READY。

## 验收

- 各受控宿主发现边界映射到稳定 detail code；未知异常仍退回泛化能力不可用且不泄漏异常文本。
- receipt 完整性摘要覆盖 detail code，旧无字段 receipt 仍能读取。
- 工程等待调查结果包含具体中文下一步，原 Task/source/批准/等待状态不变。
- 增量 Python 单元/契约测试、schema 同步、Ruff、改动文件 Mypy 通过。

## 存量与回滚

旧 receipt 不回写、不猜测历史根因；用户需在修复后的同一需求重新调查获得新诊断。回滚只回退服务代码，
不删除 immutable receipt、Operation 或 Task，不自动解除等待。
