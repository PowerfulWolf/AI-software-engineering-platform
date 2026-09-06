# T044 第一阶段：中断 Coder 改动的只读捕获

## 本阶段成果

- `GitWorktreeManager.capture_changes/verify_capture` 绑定原 Coder 身份、完整 HEAD、变更文件摘要、
  实际补丁和暂存区 diff 摘要；不修改文件、index、分支或 Task。
- 重用现有 ownership/path/read/write/deny/filter 守卫；拒绝现场漂移、越权、秘密、二进制、
  软链接、特殊文件、超限和第一版不支持的新增/删除/改名等情形。
- 使用零上下文补丁并去掉 hunk 标题中的非编辑文本，避免复制相邻未改动的测试秘密样例；
  实际变更行的敏感检测仍然生效。
- 新增独立 [恢复契约](../../.trellis/spec/core/delivery-recovery.md)，同步 Git 文档、规范索引和
  AGENTS。README 使用方法未改：当前尚未新增可用的恢复命令。

## 验证

- 23 项只读捕获测试；真实临时 Git 验证捕获字节、拒绝场景及补丁在临时 checkout 上的可应用性。
- 最终全量 **800 passed /139.05s**，包括专用 MySQL 测试库；Ruff/format、strict Mypy
  （258 files）、offline lock、sdist/wheel 与 diff-check 通过。
- 用原 Context 的权限只读检查真实中断现场：15 个文件、19,749 字节补丁；重验通过，index bytes
  和 HEAD 不变。仅计算内存捕获，不保存/应用需求补丁。本轮真实模型调用为 0。
- 仅在 macOS 验证；无 Linux 机器实测。目录 fd/O_NOFOLLOW 等接口面向 macOS/Linux。

## 尚未完成

T044 **不是完成状态**。后续仍需不可变恢复计划/人工授权、已批准上游内容的显式继承、新基线
校验、新 Task/dispatch/run、受绑定的补丁应用、CLI 幂等恢复及真实 Coder→QA→Reviewer 验证。
旧失败记录不可复活，已有代码不可当作候选提交或验收通过。源码修复由 Astra 完成，不计作平台
自主需求交付。没有推送、需求分支合并或部署。

回滚：回退本阶段独立提交；没有数据库迁移、运行记录改写或原 Coder 工作区变更。
