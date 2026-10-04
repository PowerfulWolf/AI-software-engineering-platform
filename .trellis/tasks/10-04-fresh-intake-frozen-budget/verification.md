# 增量验证

- 修复前：真实临时 Git 仓库 6 份规范约 1.3 MB 被旧 aggregate 拒绝；SIGTERM dirty run 被 stderr 认证词误报；已复现。
- 修复后：相关 joint context、requirement retirement、blocker_text、Codex CLI 四模块增量 76 passed (9.99s)。增加 SIGINT/SIGKILL 参数后，affected dirty/auth/signalled 选择 10 passed (1.07s)。未跑全量。
- 五个生产文件 mypy 通过；九个 Python 文件 Ruff check 通过，格式化与 diff check 完成。
- 约 1.3 MB 全文/hash 保留且 reference prompt 小于 10 KB；约 4.4 MB 拒绝；拒绝 checkpoint 可正式 CLOSED。
- 存量：旧 K1 Close Operation operation_60203e1f0d5f6da9df3b8aa60b908603 为 SUCCEEDED，父 CLOSED；旧 Coder 基线 3c47636、6 文件保留；新 Create operation_bd2ec8d7ce12164a0d49bf0f2b3eaba2 的失败历史保留。重载后以 typed Create/删除草稿处置遗留 PREPARING，之后在新基线重新创建。
- 尚未实际浏览器验收；使用 Console API 和自动回归核对状态，实际需求独立 QA/Review 尚未完成。
- 回滚：revert 本次提交并在空闲时重启，保留所有 journal、Run、Task 和 worktree。
