# T027 Verification

- `pytest -q tests/visualization`：2 passed；
- Ruff check/format：passed；
- strict Mypy：passed；
- `git diff --check`：passed。

Known limitation：T026 尚未提供 Agent 总 capacity、cost 或完整 HumanActionEvent，renderer 不猜测
这些事实，保留明确的 unknown/空值；后续可向下兼容增加字段。
