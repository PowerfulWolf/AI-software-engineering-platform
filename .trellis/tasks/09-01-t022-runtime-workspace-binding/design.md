# T022 Design

## Boundaries

```text
OrganizationWorkspace + ProjectWorkspaceManifest + target project root
        │ validated binding
        ▼
RuntimeWorkspaceBinding + RuntimeConfig/RuntimePaths
        │ per-run assignment/model/context resolution
        ▼
AgentRunAllocation → existing serial TaskOrchestrator
```

Binding 层只负责路径和身份组合；TaskOrchestrator 仍是 TaskStatus 唯一写入者。所有 workspace
路径必须显式、绝对、经过 manifest 校验；目标项目是代码 cwd，sidecar 是平台事实根，组织 root
是 Agent/Model/WorkQueue 的事实根。

## Files owned by this task

- `src/ai_software_engineer/runtime.py` 或新增 `src/ai_software_engineer/runtime_workspace.py`；
- `schemas/runtime-workspace-binding.schema.json`（若需要）；
- `tests/runtime_workspace/**` 与相关 runtime composition tests；
- 本 task 的 `.trellis/tasks/**` 记录。

共享 docs/spec 由 root 在所有依赖汇合后统一更新。
