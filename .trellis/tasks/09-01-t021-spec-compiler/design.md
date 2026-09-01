# T021 Design

## Boundaries

```text
platform hard policy + ProjectProfile native rules + Task constraints
        │ precedence + conflict detector (pure)
        ▼
CompiledSpec | SpecConflict
        │
        ├─ no conflict → Context source for Agent Run
        └─ conflict → SPEC_CONFLICT + WAITING_HUMAN route fact
```

SpecCompiler 只产生规则事实和 resolution request，不替 Orchestrator 写状态、不为 Agent 授权，
也不修改项目文件。硬安全规则的优先级不能通过人工 resolution 降低；工程冲突的 resolution
必须保留双方来源和 operator identity。

## Files owned by this task

- `src/ai_software_engineer/spec_compiler.py`；
- `schemas/spec-resolution.schema.json` 和/或 `schemas/spec-conflict.schema.json`；
- `tests/spec_compiler/**`；
- 本 task 的 `.trellis/tasks/**` 记录。

共享文档由 root 在 T019/T020/T021 汇合后更新。
