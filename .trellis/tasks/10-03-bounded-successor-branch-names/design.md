# 设计

`successor_branch(original, purpose)` 在解析 `ai/<kind>/<slug>` 后，从 slug 尾部移除连续的
平台生成后缀，再追加当前 purpose。这样 `trends-recovery-review-fixes-recovery` 的下一轮
仍从 `trends` 派生。没有后缀的业务 slug 保持原样，`None` 继续表示旧的无命名 Task。

调用方继续负责读取 Git 分支占用事实；同一 delivery lineage 的重复 successor 在稳定 Product
根上按 `-2`、`-3` 等确定性限定选择空闲 ref，其他需求的碰撞仍 fail closed。该修复不做截断、
rename、rebase 或历史数据迁移。

同一恢复域还识别首个 Coder 启动前的 `WorktreeAlreadyExists`：只有 `NEW → PLANNING →
IMPLEMENTING` 事件、无 artifact/context/model invocation/claim/admission/candidate/worktree
证据时才生成 `pre_agent_worktree_conflict` 精确重启计划；Manager 的协调建议不能替代该审批。
