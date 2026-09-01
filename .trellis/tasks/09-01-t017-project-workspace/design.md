# T017 设计

## Boundary

```text
operator gives project_root
          │ read-only canonicalization
          ▼
ProjectWorkspaceRegistry
          │ external sidecar only
          ▼
<registry_root>/<project_id>/
  workspace.json
  profile/ agents/ knowledge/ policy/ state/
  artifacts/ contexts/ evidence/ evaluations/
  handoffs/ runs/ locks/ logs/ spec-conflicts/
```

`project_root` 是真实代码 cwd；`ai_workspace_root` 只是平台数据根。T017 不复制源码、不把
平台状态写回目标仓库，也不决定项目原生规范的语义。后续 Runtime 可以选择 role worktree
作为临时代码 checkout，但仍以 manifest 的 `project_root` 作为逻辑项目绑定。

## Identity and safety

- Project ID 默认由 canonical project root 的短 SHA-256 与清理后的 basename 组成，保证同一路径
  稳定、同名不同路径可区分；操作者提供的 ID 只接受 `project_...` pattern；
- registry root 和最终 sidecar path 都要经过 lexical + resolved containment 检查；sidecar 与
  project root 互不包含；existing symlink、文件占位和 registry 内越界路径拒绝；
- 创建先在 registry root 下生成隐藏 staging 目录，再写入 fsync 后的 `workspace.json`，最后
  用 rename 发布。目标路径发生并发占用时只读取并校验现有 manifest，不覆盖任何数据；
- manifest 使用排除 `manifest_sha256` 自身后的 canonical JSON digest，任何正文变化都在复用前
  fail closed；
- 已有 workspace 不自动修复：manifest 缺失、JSON 损坏、layout 缺失或 project binding 改变都
  进入稳定错误，避免悄悄篡改组织知识和审计现场。

## Future composition points

- T018 在 `profile/` 记录 ProjectProfile 与项目管理工具探测结果；
- T019 在 `knowledge/` 建立 project-native rule 索引，并由 SpecCompiler 生成冲突 artifact；
- T020 将 Runtime 的 SQLite/Artifact/Context/Evaluation/Handoff 路径绑定到 manifest；
- T021/T022 将命令 stdout/stderr、diff、测试和 Agent token usage 写入 `evidence/` 与 `runs/`；
- T024+ 只读取 durable StateEvent、AgentRunEvent、Context manifest、Artifact 和 Evidence，生成
  可重放的 dashboard read model，不让 UI 直接驱动状态迁移。

## Good / Base / Bad

- **Good**：给定 `/work/service`，平台在 `/work/.ase-workspaces/project_service_<hash>/` 建立
  sidecar，命令 cwd 仍是 `/work/service`，日志和 Artifact 进入 sidecar；
- **Base**：空目录也能注册，后续 ProjectProfile 负责识别 Maven、Gradle、npm、Cargo、Make 或
  自定义流程；T017 不假设目标项目语言或 Git 之外的 VCS；
- **Bad**：在目标项目创建 `.ase/`、把源码复制到 sidecar、把同一个 Project ID 复用给另一个
  路径、或发现缺失目录后自动补写旧 workspace；这些都必须拒绝或升级人工。
