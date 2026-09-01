# T013 — CLI/runtime composition

## Goal

把 v0.1 的 typed domain、SQLite、Evaluation 和 Handoff 能力组装成一个可直接操作的离线 CLI，
让人类可以创建/查看 Task、读取状态事件、重算评估报告和生成交付 handoff。

## Scope

- 增加 `ase task create/show/events` 命令；
- 增加 `ase evaluation report` 命令，从 durable stores 重算 metrics/ADR；
- 增加 `ase handoff build` 命令，输出不可变 JSON/Markdown handoff；
- 所有命令使用 typed Pydantic/JSON Schema 入口，错误无 traceback、fail closed；
- 保持 v0.1 串行边界，不在本任务引入新的 Agent、DAG、队列、数据库或自动 merge。

## Acceptance criteria

- [ ] `ase task create --file task.json` 能校验并持久化一个 `NEW` Task；非 `NEW` 或非法 JSON 被拒绝；
- [ ] `ase task show` 和 `ase task events` 输出可重新解析的 canonical JSON；
- [ ] `ase evaluation report` 能从 SQLite、ArtifactStore、EvaluationEventStore 重算报告；
- [ ] `ase handoff build` 仅接受 `DONE/BLOCKED`，持久化 JSON + Markdown 并返回路径；
- [ ] 所有用户输入错误返回非零退出码且不泄露 traceback/secret；
- [ ] CLI contract tests 覆盖 good/base/bad cases，现有全量测试保持通过。

## Contract impact

- 不改变既有 wire Schema；新增 CLI 参数契约和 runtime path defaults；
- 更新 `docs/`、`AGENTS.md` 与 `.trellis/spec/core/python-runtime.md`，记录 CLI composition seam。

## Validation

```text
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

## Rollback

删除 T013 CLI 子命令和新增测试/文档即可；不会修改既有数据库 Schema、Artifact 或事件格式。
