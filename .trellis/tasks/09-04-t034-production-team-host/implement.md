# T034 Implementation

## Completed

- [x] Production Team Host 与 secret-free 配置加载；
- [x] MySQL TaskRepository、dispatch authority 与独立 Docker Compose；
- [x] GPT-5.5 Responses API typed adapter；
- [x] Codex CLI provider 与 GPT→Qwen→DeepSeek typed fallback；
- [x] Product/Designer/Planner production producer；
- [x] Coder/QA/Reviewer policy-bound tool loop；
- [x] offline scripted-provider E2E 与显式 opt-in live smoke；
- [x] README、runtime 文档、Trellis executable contract 与阶段 archive。

## Verification

- `ASE_TEST_MYSQL_DSN=... uv run pytest -q`：`651 passed`；
- `uv run ruff check .`、`uv run ruff format --check .`：通过；
- `uv run mypy src tests`：通过；
- `uv lock --check`、`uv build --offline`、`git diff --check`：通过；
- scripted provider 使用真实 MySQL、真实 Git commit 和隔离 worktree 到达 `DONE`；
- live GPT-5.5 已验证 Product structured output，并实际推进 Product→Designer→Planner→dispatch。当前
  Codex desktop 宿主中的 Coder 因 macOS 禁止嵌套 `sandbox-exec` 而停止；Production 默认 sandbox 未
  降级。应从普通本地终端运行 `scripts/smoke-live-gpt55.sh` 完成宿主验收。
