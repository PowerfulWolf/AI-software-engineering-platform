# 平台语义分支命名

## 目标

用户看到 ASE 候选分支即可理解它是新增能力还是问题修复，以及具体改什么。不依赖 Task ID 解读需求。

## 已确认需求

- R1 新分支格式为 `ai/feature/<需求语义短名>` 或 `ai/bugfix/<问题语义短名>`；不要随机/哈希 ID 或 `attempt-N`。
- R2 平台生成与校验同时落实；不能只有提示词约定。短名不得因运行重试而随机变化。
- R3 正常同一 Task 的续跑保留分支；QA/Reviewer 保持同候选独立 detached worktree。
- R4 新需求、修复和恢复入口遵守同一规则；旧分支/旧 artifact 保持可读可恢复，不批量重命名，不修改历史哈希。
- R5 分支碰撞不得覆盖或误领另一需求的工作；需求语义与平台身份分开存储。
- R6 规范、持久化/Schema 契约和真实 Git 回归一起更新。
- R7 用户已确认类型按原始需求性质固定：feature 的 QA/Review 返工与恢复仍保持 feature；只有独立缺陷修复需求使用 bugfix。

## 已知事实

- `git/worktree.py:LocalGitWorkspace._branch_name` 从 Task ID/attempt 硬编码旧格式。
- `recovery/models.py:CapturedChanges.to_capture` 再次硬编码同一格式；只改创建会使恢复身份校验失效。
- `WorktreeSpec` 目前只有 Task、role、attempt、source revision，没有可验证的分支命名意图。
- 恢复/修复可能建立新 Task，旧现场必须保留；不能把不同 Task 直接当普通 retry 共用脏现场。
- `domain/project_delivery.py:derive_delivery_task` 从已批准 ProductSpec 派生 Task；`manager/production_agents.py:ProductDraft` 尚无结构化需求类型/短名。
- `role_workspace.py:DispatchRoleWorktreeCoordinator.open_coder` 将 Coder checkout 固定到 attempt 1，普通运行次数并不要求新建分支。
- `recovery/remediation.py:CandidateRemediationService.prepare` 在 QA/Review 否定或获批前提修复后生成新 `task_continue_*`，沿用原 ProductSpec。

## 验收标准

- AC1 正常 feature 和 bugfix 新需求实际 Git 分支符合 R1，名称描述目标，不出现平台 ID/轮次。
- AC2 缺失、非法/危险或碰撞的分支意图在写入 Git 前拒绝；无覆盖、强制 checkout 或扩大权限。
- AC3 同 Task 重启/续跑复用已绑定名称；源 revision、worktree owner 或 branch 漂移仍拒绝。
- AC4 新格式捕获、恢复、候选交付形成闭环；历史无新字段记录的 bytes/hash 与恢复行为不变。
- AC5 QA/Reviewer 始终独立验证同候选；前端交付结果显示实际分支，不从 Task ID 推测。

## 范围与限制

改 ASE 平台，不改目标业务代码，不执行真实模型交付，不重启服务。初始实施阶段不 commit/push；
验证报告交付后，用户明确要求完成任务并提交、推送，收尾据此执行。
保留当前 README/TODO 文档变更。实现方案需检查命名来源、审批绑定、独立修复 Task 与同名冲突处理后收敛。
