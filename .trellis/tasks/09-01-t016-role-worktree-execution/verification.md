# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache PYTEST_ADDOPTS='-p no:cacheprovider' uv run --offline pytest -q`：270 passed。
- `UV_CACHE_DIR=/tmp/ase-uv-cache RUFF_CACHE_DIR=/tmp/ase-ruff-cache uv run --offline ruff check .`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline ruff format --check .`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache MYPY_CACHE_DIR=/tmp/ase-mypy-cache uv run --offline mypy src tests`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv build --offline --out-dir /tmp/ase-dist-t016-20260901`：成功生成 sdist 与 wheel。
- `git diff --check`：通过。

## 关键反例

- Coder spec 与 QA AgentDefinition 角色不一致时在 Git 创建前拒绝；orchestrator 没有合法
  `WorktreeSpec`，不能获得业务命令 executor。
- 命令结果的 cwd 等于 manager-issued worktree；QA/Reviewer 的 detached candidate 与输入
  revision 一致，session 不复制 branch/layout 或绕过 T006 manager。
- dirty worktree 关闭失败且 changed paths 保留，清理只有在证据已处理并恢复 clean 后才成功；
  非法 executor settings 在 session 构造阶段拒绝，不留下 worktree 或 attempt branch。

## 边界

T016 只组合 Git worktree 与 T015 command executor，不迁移 Task、不写 Artifact、不生成 verdict，
也不自动 merge/deploy。未来 Runtime/role service 必须显式把 `CommandResult` 转成 evidence；
单机 subprocess 仍不是完整的 OS/container sandbox。
