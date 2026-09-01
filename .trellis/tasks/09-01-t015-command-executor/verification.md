# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache PYTEST_ADDOPTS='-p no:cacheprovider' uv run --offline pytest -q`：265 passed。
- `UV_CACHE_DIR=/tmp/ase-uv-cache RUFF_CACHE_DIR=/tmp/ase-ruff-cache uv run --offline ruff check .`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline ruff format --check .`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache MYPY_CACHE_DIR=/tmp/ase-mypy-cache uv run --offline mypy src tests`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv build --offline --out-dir /tmp/ase-dist`：成功生成 sdist 与 wheel。
- `git diff --check`：通过。

## 关键反例

- 允许命令以固定 worktree cwd 执行，shell 控制 token、未授权可执行文件和缺失 workspace 均在
  subprocess 启动前拒绝。
- 宿主机 `ASE_SECRET` 不会进入子进程；显式 allowlist 才能注入变量，stdout/stderr 超过预算时
  保留前缀并标记截断。
- 超时异常不携带命令输出，并终止整个进程组；非零退出只表达执行事实，不被解释成 PASS。

## 边界

T015 只交付单机、可替换的命令执行端口，供后续 Runtime/QA/Coder application service 接入。
它不负责 acceptance criteria、Task 状态迁移、Artifact 写入、自动 merge/deploy，也不允许通过
完整宿主环境、shell 拼接或工作区外 cwd 扩大权限。
