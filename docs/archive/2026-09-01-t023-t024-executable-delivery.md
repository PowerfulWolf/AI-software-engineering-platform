# T023–T024：可执行交付边界

## 阶段快照

- 日期：2026-09-01
- 里程碑：M6 可执行交付（执行安全与证据边界）
- 纳入任务：T023 Evidence capture、T024 Coder/QA/Reviewer typed tool protocol
- feature/integration commit：`02b3183`

## 形成的能力

1. `RunEvidenceSession` 与 `FileEvidenceStore` 封存 command、diff、test 和 Agent usage facts；
   统一脱敏、UTF-8 上限、canonical SHA-256、atomic write、immutable replay 和 run manifest。
2. Agent `AgentUsage` 与 OpenAI-compatible adapter usage extraction 让 token 成本进入可审计证据，
   不把 provider 原始响应穿透到领域层。
3. `PolicyBoundToolRegistry` 只暴露 typed `read_file`、`write_file` 和 tokenized `run_command`；
   request/result 带 run/role/operation identity，shell、verdict、artifact、state mutation 不在协议中。
4. Runtime workspace binding 新增独立 `evidence/` 与 `runs/` roots，`RuntimeSession` 初始化
   `FileEvidenceStore`；sidecar 与目标项目代码仍保持物理隔离。
5. Python↔JSON Schema contract tests 覆盖 evidence、manifest 和 tool result wire payload。

## 验证证据

- 全量 pytest：366 passed
- Ruff check：passed
- Ruff format --check：262 files formatted
- strict Mypy：127 source files，无问题
- `uv build --offline`：sdist/wheel 均成功
- `git diff --check`：passed

## 已知限制与下一步

- T024 tool result 目前是 application seam，尚未自动包裹每个真实 role adapter 调用；接入 T025
  时必须显式使用 `RunEvidenceSession`，不能给 Agent 直接 filesystem/subprocess handle。
- M6 仍不自动 merge protected branch；跨语言真实项目串行交付由 T025 验证。
- T026 将从 durable StateEvent、Evaluation、Artifact、Evidence、Handoff facts 构建只读投影，
  T027 再基于投影实现工作可视化。
