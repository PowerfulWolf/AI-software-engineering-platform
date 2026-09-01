# T017 实现记录

## Changes

- 新增 `ProjectWorkspaceManifest`、固定 `WorkspaceLayout`、`ProjectWorkspace` handle 和
  `ProjectWorkspaceRegistry`；
- 新增 `project-workspace.schema.json`，约束绝对路径、Project ID、layout 和 timestamp；
- 新增 registry contract tests，覆盖幂等、ID collision、外置边界、目标目录不变、损坏 manifest
  与缺失目录；
- 更新 README、architecture、milestones、AGENTS 和 `.trellis/spec/`，将 sidecar 与未来的
  event-driven visualization 设为后续契约。

## Verification

- 全量 pytest：283 passed；
- Ruff lint 与 format check：通过；
- strict Mypy：92 source files 通过；
- source distribution 与 wheel build：通过；
- `git diff --check`：通过。
