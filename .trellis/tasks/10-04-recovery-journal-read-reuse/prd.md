# 恢复预检的联合历史复用

## 目标与证据

K1 exact recovery 审批已持久化，但约 8 分钟才建立新工作区。采样主要在 JSON 编码校验；需求目录共有约 237 MB JSON，原生恢复多次 `_parent → JointJournal.current → history` 重读、解析并重新封存验证。数据库 dispatch 总正文仅约 638 KB。

## 契约与范围

`JointJournal.history/current` 对未变更字节复用本实例已验证 checkpoint 与 successor 边界；每次重读文件、计算真实字节摘要和检查路径。返回深复制对象，调用方不得通过可变 dict 污染缓存。缓存有明确容量界限。任何变更必须重新解析校验；删除、增添、链断裂和 symlink 均仍被发现。

原生恢复 Reader 持有按 Project requirements root 隔离的 journal；同一 Entry 的审批、封存及执行事实验证复用同一只读 verifier。每次 inspect 仍重验当前 source/target，缓存不授予运行或审批权限。

## 验收

- 重复读取相同历史不重复调用重型 checkpoint decoder，新增 checkpoint 只校验新记录及新边界。
- 篡改正文、历史缺口、链变化及 symlink 必须拒绝；返回对象中的 attempts dict 修改不得污染后续读结果。
- 正常 append、原生失败 Coder 来源恢复契约仍通过；真实交付不被中断。
- 存量数据无需迁移；有界实例缓存消失后仍重新完整验证，原文件和审计历史不变。

## 验证命令与回滚

运行 `pytest tests/manager/test_joint_journal_read_reuse.py`、相关 joint contract 与 native recovery 单项、Ruff/mypy/diff。空闲时回退本任务提交并重启；保留所有持久事实。
