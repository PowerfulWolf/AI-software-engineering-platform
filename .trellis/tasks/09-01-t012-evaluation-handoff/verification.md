# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache uv run pytest -q`：239 passed；包含 5-case ADR suite、
  Evaluation emitter/store/trace tests、DONE/BLOCKED handoff 与 JSON Schema contract tests。
- `uv run ruff check .`、`uv run ruff format --check .`：通过。
- `uv run mypy src tests`：strict mode 通过，共检查 80 个 source files。
- `uv lock --check`、`uv build`、`git diff --check`：通过。

## 关键反例

- DONE 缺 regression window 为 `PENDING`；人工改码/测试、uncaught policy violation、回归
  FAIL 均不进入 ADR 分子。
- Agent run 与 Artifact producer identity 不同、DONE 四制品链断裂、case/base/task identity
  不同均 fail closed。
- Evaluation event exact replay 幂等；changed replay、合法字段篡改、非法 lookup 拒绝。
- 非终态 handoff、DONE 断链、Handoff Markdown 篡改拒绝；等价重建保留首次观察时间。

## Cross-layer check

数据流已核对为 `AgentAdapter → EvaluationEventStore → TraceBuilder → EvaluationEngine` 与
`TaskRepository + ArtifactStore → HandoffBuilder → FileHandoffStore`。Python types、两个新增
JSON Schema、README/docs/AGENTS/Trellis spec 与 contract fixtures 使用相同 enum/字段；包级
import smoke test 通过。各 store 保留 adapter-owned canonical/atomic helper，未新增跨层共享 I/O
依赖或数据库迁移。

## v0.1 边界

Evaluation/Handoff 通过库级 public seams 装配；human/regression events 仍由可信外部执行器记录。
本任务不增加 dashboard、自动 merge/deploy、并行 DAG、向量库或 PostgreSQL migration。
