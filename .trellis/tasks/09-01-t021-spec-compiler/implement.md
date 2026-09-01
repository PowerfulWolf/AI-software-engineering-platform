# T021 实现记录

## Changes

- 新增 structured `SpecRule`、`CompiledSpec`、`SpecConflict`、`WaitingHumanRoute` 与
  `SpecResolution`；
- 编译平台 hard/engineering、ProjectProfile-backed project rules 与 TaskConstraints；相同输入
  产生稳定 compilation/conflict hash；
- opaque Markdown 只作为 URI/hash 来源保留，不假装自动理解任意自然语言规范；
- 重叠 scope 的不同值不按优先级静默覆盖，而是生成 `SPEC_CONFLICT` 并路由
  `WAITING_HUMAN + release_lease + preserve_task_checkpoint`；
- resolution 必须包含 operator、rationale、evidence，并绑定精确 conflict SHA；hard safety 只能
  保留 hard rule、更新 lower rule 或终止，不能选择 lower rule 覆盖；
- 新增 sidecar `spec-conflicts` 下的 atomic append-only conflict/resolution store；
- 新增 canonical conflict/resolution JSON Schema。

## Verification

- SpecCompiler 定向测试：10 passed；
- 合同与 Schema 定向测试：44 passed；
- 全量测试：334 passed；
- Ruff lint/format、strict Mypy、offline build 与 `git diff --check` 通过。
