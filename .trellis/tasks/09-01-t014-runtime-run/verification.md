# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache PYTEST_ADDOPTS='-p no:cacheprovider' uv run --offline pytest -q`：250 passed。
- `UV_CACHE_DIR=/tmp/ase-uv-cache RUFF_CACHE_DIR=/tmp/ase-ruff-cache uv run --offline ruff check .`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline ruff format --check .`：163 files already formatted。
- `UV_CACHE_DIR=/tmp/ase-uv-cache MYPY_CACHE_DIR=/tmp/ase-mypy-cache uv run --offline mypy src tests`：通过，83 个 source files。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv build --offline`：成功生成 sdist 与 wheel。
- `git diff --check`：通过。

## 关键反例

- RuntimeConfig 拒绝明文 `api_key`、未知字段、重复 role override 和非法环境变量名。
- RuntimeSession 在缺少必需 API key 时不打开运行；终态 Task 不会追加状态或 Evaluation 事实。
- RuntimeSession 的 fake adapter e2e 验证四角色串行顺序、CaseStartedEvent 幂等边界和 typed
  Artifact/Context 持久化；真实 provider 仍通过相同 `AgentAdapter` seam 接入。

## 边界

T014 只提供 operator-owned RuntimeConfig 与单仓库串行 `ase task run`。不引入复杂 DAG、
并行 Agent、消息队列、向量库、容器 sandbox、自动 merge 或部署；API key 永不进入配置、
context、artifact 或错误输出。
