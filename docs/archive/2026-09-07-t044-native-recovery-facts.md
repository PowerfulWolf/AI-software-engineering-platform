# T044 C1：原始交付事实的只读校验

## 本阶段成果

- NativeRecoverySourceReader 从真实公司/项目 sidecar 和 MySQL 读取失败 Task、dispatch、状态链、
  已批准 Product、Designer/Planner 完成记录、原 preparation，以及失败 Coder 的 context/route。
- 联合需求的父审批与子交付归属由平台核对，调用方不能选择忽略父需求。
- 五类原生记录存储新增显式 read_only：检查不能初始化目录、发布记录或获取写入 fence。
- 源码基线 `70bcb29`；本记录所在提交为本阶段提交，分支 `feat/t044-native-recovery-facts`。

## 验证

- 全量 **850 passed /84.30s**，包括专用 MySQL 测试库；Ruff/format（485 files）、Mypy
  （269 files）、offline lock、sdist/wheel 和 diff-check 通过。
- 离线单仓/双仓完整生产夹具模拟 Coder 留下改动后失败，验证重复只读检查、不写项目/sidecar，
  以及缺失/篡改审批、方案、父需求、run/context 等拒绝场景。
- 实际 round3 只读检查通过：Task BLOCKED/revision3，原 child `b67e1691`、parent `617b6514`、
  base `68f8f8c`，22 个 write allowlist 条目和 13 个 deny 条目。没有新审批或恢复 Task。
- 未调用真实模型、未修改需求 worktree、未推送 GitHub。仅 macOS 实测，Linux 仍待验证。

## 真实边界

这是 Astra 修复平台，不是平台完成目录需求。T044 仍在进行中；原始事实读取并不等于授权新
基线上的执行。剩余：目标 preparation/当前规范复核、明确继承上游内容、人工恢复入口、
新 Task/dispatch/补丁应用，最后由真实 Coder→QA→Reviewer 交付。

SQL 读取使用一致性只读事务，跨 Git/文件/SQL 的两次检查不是全局锁；调用方需确保旧执行已停止。
旧 checkpoint 使用命令时间，不能用它和模型完成时间的先后关系推断事实归属。
回滚：回退本阶段源码提交；没有数据库迁移、旧业务记录改写或目标项目改动。
