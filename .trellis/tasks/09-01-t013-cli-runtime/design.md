# T013 设计

## CLI 边界

`src/ai_software_engineer/cli.py` 作为 composition root，只负责参数解析、打开 concrete adapter、
序列化输出和稳定错误映射；业务规则仍由 `Task`、`SqliteTaskRepository`、`EvaluationTraceBuilder`
和 `HandoffBuilder` 执行。CLI 不直接写 SQL、解析 Agent payload 或推进状态。

## 命令

```text
ase task create --file TASK_JSON [--database PATH]
ase task show TASK_ID [--database PATH]
ase task events TASK_ID [--database PATH]
ase evaluation report CASE_ID [--database PATH] [--artifacts PATH] [--events PATH]
ase handoff build TASK_ID [--database PATH] [--artifacts PATH] [--output PATH]
```

默认路径只指向本地 `.ase/` 和 `artifacts/`，所有路径可显式覆盖，便于测试和部署。

## 输出/错误契约

- 成功输出 JSON；handoff build 额外返回 JSON/Markdown 路径；
- `task create` 只允许 `status=NEW`、`attempts=0`，避免绕过状态机；
- 文件不存在、JSON/Pydantic 校验失败、Task 不存在、case/handoff 不可用均输出一行
  `error: ...` 到 stderr，退出码 2；不显示 traceback；
- 任何持久化写入仍由现有 immutable/transactional store 完成。

## 数据流

```text
CLI args
  → typed Task / TaskId
  → SqliteTaskRepository / FileArtifactStore / FileEvaluationEventStore
  → TraceBuilder + Engine 或 HandoffBuilder + HandoffStore
  → canonical JSON stdout
```

## Good / Base / Bad

- Good：创建合法 NEW Task，重开 SQLite 后 show 与原 JSON 等价；
- Base：读取不存在 Task/case 或非终态 handoff，稳定非零退出且无副作用；
- Bad：CLI 直接把 `status` 改为 DONE、绕过 artifact gate 或接受裸 dict，必须拒绝。
