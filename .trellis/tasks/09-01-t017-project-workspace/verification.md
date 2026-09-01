# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache PYTEST_ADDOPTS='-p no:cacheprovider' uv run --offline pytest -q`：283 passed。
- `UV_CACHE_DIR=/tmp/ase-uv-cache RUFF_CACHE_DIR=/tmp/ase-ruff-cache uv run --offline ruff check .`：通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline ruff format --check .`：185 files 通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache MYPY_CACHE_DIR=/tmp/ase-mypy-cache uv run --offline mypy src tests`：92 source files 通过。
- `UV_CACHE_DIR=/tmp/ase-uv-cache uv build --offline --out-dir /tmp/ase-dist-t017`：成功生成 sdist 与 wheel。
- `git diff --check`：通过。

## 关键反例

- sidecar registry 位于目标项目内、registry root 是 symlink、目标目录缺失或 Project ID 已绑定
  另一目录时，注册在发布任何 workspace 前拒绝；目标项目内容保持不变。
- `workspace.json` 缺失、固定 layout 缺目录、路径身份不匹配或 Schema-valid 正文被改写时，
  manifest Schema/canonical SHA-256 校验 fail closed，不自动修复组织状态。
- 模拟 manifest 写入失败后，本轮隐藏 staging 目录被完整清理，不发布半成品 workspace。
- 可视化路线只消费 StateEvent、AgentRunEvent、Context、Artifact、Evidence、Evaluation 和
  Handoff 的只读 projection，不让 UI 成为第二个状态/verdict 写入者。

## 边界

T017 只建立目标项目与外置 AI sidecar 的绑定、固定目录和 wire contract；尚未自动发现语言、
构建/VCS、项目原生规范或 ProjectProfile，也尚未把 T014 Runtime paths 自动绑定到 sidecar。
这些分别属于 T018–T020。真实 Agent tool loop、evidence capture、跨语言目标项目 e2e 和 dashboard
属于 T021–T025；本任务不引入 DAG、向量库、队列、自动 merge 或 UI 状态写入。
