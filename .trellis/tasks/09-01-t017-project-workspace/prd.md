# T017 — 外置 Project Workspace 注册与初始化

## Goal

为任意本地目标项目建立稳定的 `project_root → ai_workspace_root` 绑定。目标项目继续是
实际代码、测试和构建命令的工作目录；平台只在外置 sidecar workspace 保存 Agent、规范、
ProjectProfile、Task 状态、Context、Artifact、Evidence、Evaluation、Handoff 和日志。

## Requirements

- 新增 typed `ProjectWorkspaceManifest`、`ProjectWorkspace` 和 `ProjectWorkspaceRegistry`；
- 自动生成稳定且不泄露完整路径的 Project ID，也允许操作者提供合法 Project ID；
- sidecar workspace 必须在目标项目外，不能通过路径或 symlink 与目标项目重叠；
- 注册必须幂等；同一 ID 指向另一项目时拒绝；旧 manifest、缺失目录和非法 JSON fail closed；
- 初始化采用 staging + 原子 rename，不复制源码，不创建目标项目内的 `.ase` 或 AI 文件；
- `workspace.json` 必须带 canonical SHA-256，读取时检测 Schema-valid tampering；
- 创建规范化目录：profile、agents、knowledge、policy、state、artifacts、contexts、evidence、
  evaluations、handoffs、runs、locks、logs、spec-conflicts；
- 提供 JSON Schema、contract tests 和文档，为后续 ProjectProfile、SpecCompiler、Runtime 绑定
  与 Agent 工作可视化提供稳定路径；
- 不改变现有 Task/Agent/Artifact wire Schema，不接入 DAG、向量库、队列、容器或自动 merge。

## Acceptance Criteria

- [x] 同一目标项目重复注册返回相同 Project ID、sidecar 路径和首次 manifest；
- [x] 初始化只改变外置 registry root，目标项目内容和目录保持不变；
- [x] 非法目标目录、sidecar 位于目标项目内、symlink escape、Project ID 冲突和损坏 layout 均拒绝；
- [x] 14 个 sidecar 目录与 `workspace.json` 按固定布局创建；
- [x] Python model 与 `schemas/project-workspace.schema.json` 通过正向/反向契约校验；
- [x] 文档明确目标代码目录、AI sidecar、native project rules 与未来可视化读取边界；
- [x] 全量测试、Ruff、strict Mypy、build、diff check 通过。

## Contract Impact

新增 `src/ai_software_engineer/project_workspace.py`、`schemas/project-workspace.schema.json`、
`tests/project_workspace/`、项目架构/里程碑/可视化文档和核心规范；不修改既有 Task、Agent、
Artifact、Context 或 Runtime wire Schema。

## Rollback

删除 T017 模块、Schema、测试、文档和任务记录；现有 T001–T016 的 repository、Artifact、
Context、Git、Runtime 与 role worktree 契约保持不变。
