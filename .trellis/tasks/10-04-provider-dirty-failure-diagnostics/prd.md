# 保留 Responses 提供方失败诊断并正确展示恢复阻塞

## Goal

让 Coder 的 Responses 路由在“提供方失败但工作区已有改动”时保留可审计的安全诊断，并让准备摘要漂移的交付在控制台显示真实阻塞状态和可执行的恢复动作。

## Scope

- 复用既有 `safe_diagnostic` 和 HTTP 诊断契约，不扩大模型、文件或命令权限。
- 保留 `POLICY_VIOLATION` 和 dirty worktree 现场，禁止自动 fallback、reset 或伪造 Artifact。
- 状态读接口不改写历史 checkpoint，只在 projection 中把 drift 诊断映射为阻塞动作。

## Acceptance criteria

- [ ] HTTP 429/5xx、传输异常在 dirty worktree 场景下提供安全、限长、脱敏的原因摘要。
- [ ] dirty failure 仍不可重试，不产生候选或 QA/Review 结论。
- [ ] preparation drift 不再同时显示可直接 RUN_DELIVERY 的动作。
- [ ] 只运行相关增量测试，并同步规范中的 failure mode。

## Rollback

回滚本次代码提交即可；保留 `.ase` 中既有 Run、Task、worktree、checkpoint 和 approval。
