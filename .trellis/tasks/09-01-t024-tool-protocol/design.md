# T024 Design

```text
typed Agent output
        │ ToolRequest (path/argv only)
        ▼
PolicyBoundToolRegistry
  ├── WorkspacePolicy (path + command allowlist)
  ├── role hard safety (QA tests-only, Reviewer read-only)
  └── SubprocessCommandExecutor (shell=False, bounded env/output)
        │
        └── ToolResult | ToolRejectedResult
```

Registry 是每个 run 独占的 application facade；下游只消费 immutable result。任何新操作都必须
新增 typed request/result、JSON Schema、权限规则和反向测试，不能把自由文本交给 shell。
