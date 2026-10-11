# Preserve handwritten wire guards during regeneration

## Scope / interface

Applies to scripts that rebuild JSON Schema graphs from Pydantic models, including
`scripts/generate-repair-schemas.py`. Model validators are not automatically emitted
as JSON Schema cross-field conditions. A regenerated shape is therefore incomplete
until the canonical handwritten wire guards are applied.

`scripts/sync-legacy-rescue-schemas.py::guards(node)` owns legacy rescue wire gates.
The repair generator loads only its function definitions via run_path with the
script's guarded main inactive, then applies guards to every generated root and
definition. It does not run the all-schema synchronizer or depend on a prior console
output as a policy source. Engineering wait guards remain sourced from the canonical
engineering-wait-resolution schema, including current knowledge retry guards.

## Contracts

Fresh generation must retain every published allOf guard, including:

- stopped-provider permanent AUTH proof requires failed nonzero native stop and no
  output; its facts/reservation do not mix refund, receipt or other recovery proof;
- target-free stopped-provider preparation and every embedded Binding retain human
  PAUSE/proof gates, while explicit source-rebind retains its own input contracts;
- exact INSPECT provider-failure hint has start/outcome/Run provenance and no
  permitted resolution; older canonical engineering wait guards remain sourced
  from the engineering-wait-resolution schema alongside this additive hint;

- legacy BaselineExecutionReservation requires original Run, invocation start and
  containment; no sealed outcome, receipt, refunded retry or already-applied reservation;
- ExecuteExecutionBaselineIntent cannot simultaneously confirm reboot containment
  and local execution stop;
- legacy ExecutionBaselinePlan requires preserve_draft, non-conflicted input and
  an actual containment object;
- legacy ExecutionBaselineBinding requires preserve_draft, exact human engineering
  authority and containment digest;
- operator-confirmed LegacyExecutionContainment requires an empty-blocker local
  survey; other methods cannot carry that survey;
- ConsoleCommandResult READY preparation requires a rescue plan; WAITING cannot
  contain a plan, binding or approval, and both require exact delivery/checkpoint.

Do not copy only new guards or merge arbitrary previous outputs to hide omissions.
Reuse the canonical guard source and retain known future/other contract guards.
The new knowledge resolution/investigation/evidence guards must coexist with legacy
guards. Optional delivery_requirement_id remains absent from required and has a
null default for legacy wire compatibility.

## Validation matrix / tests

`tests/contracts/test_repair_schema_generation.py` runs the real generator twice in
an isolated temporary script/schema root that has no previous Console schema. It
requires byte-identical regeneration, published allOf preservation, positive and
negative independent cross-field examples for all six legacy guard families,
required new knowledge evidence, role/receipt safety, canonical engineering guard
equality and the optional parent binding. Temporary generation never writes the
repository or production schema/data. Existing local rescue and baseline schema
contract tests additionally validate full real models and payloads.

## 存量数据处置 / rollback

本问题仅影响静态 Schema 重新生成，运行服务的 Pydantic domain 校验仍保留原守卫。无需改库、
改写已有 Operation、回填审批或重建需求。修复发布恢复静态入口的原拒绝行为。回滚生成器时
不能回滚到缺失守卫的 Schema；保留已恢复的完整 wire 约束和原审计事实。
