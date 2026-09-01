# T022 实现记录

## Changes

- 新增 atomic `OrganizationWorkspace`，固定保存 AgentProfile、ModelPolicy、WorkItem/Lease 与组织
  metrics；项目 sidecar 继续只保存项目级事实；
- 新增 `RuntimeWorkspaceBinding`/Binder，把 target project code root、project sidecar 与
  organization root 绑定并在每次使用前重验 manifest/profile/binding integrity；
- 将 SQLite、Artifact、Context、Evaluation、Handoff 路径全部解析到 sidecar，禁止回落到目标
  项目 `.ase` 或相对 `artifacts/`；
- 新增 integrity-wrapped `FileOrganizationWorkforceStore`；
- 新增 `RuntimeWorkforceResolver`，校验 WorkItem、Assignment、active Lease、AgentProfile、
  ModelPolicy/Selection、Context 和 CompiledSpec 后生成 `AgentRunAllocation` 与现有
  `AgentDefinition`；
- `RuntimeSession` 支持显式 bound project root 与 workforce AgentDefinitions；多模型角色组合以
  deterministic model-set identity 记录 Evaluation case；旧显式 config/fake adapter 路径兼容；
- 新增 canonical runtime workspace binding JSON Schema。

## Verification

- T022 runtime workspace 新增测试：10 passed；
- Runtime/Schema 组合定向测试：52 passed；
- 全量测试：344 passed；
- Ruff lint/format、strict Mypy、offline build 与 `git diff --check` 通过。
