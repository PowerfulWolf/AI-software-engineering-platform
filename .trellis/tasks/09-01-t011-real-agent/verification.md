# Verification

## 结果

- `UV_CACHE_DIR=/tmp/ase-uv-cache uv run pytest -q`：213 passed；包含 20 个真实 adapter seam tests，以及 ContextStore/runner registration tests。
- `uv run ruff check .`、`uv run ruff format --check .`：通过。
- `uv run mypy src tests`：严格类型检查通过。
- `uv lock --check`、`uv build`、`git diff --check`：通过。

## 覆盖的关键反例

- HTTP 4xx/408/429/5xx、transport timeout、非法 JSON/Artifact、身份或 candidate revision 不匹配均无 Artifact/verdict。
- API key 只出现在 Authorization header，provider body 不进入错误消息。
- 相同 run ID exact replay 不重复发 HTTP；修改 request 后抛 `AgentRequestConflict`。
- endpoint userinfo、非 HTTP(S) scheme、ContextBundle cross-task/identity mismatch fail closed。
- ContextStore 验证 canonical ID、等价重放、lookup 路径、持久化篡改与原子 round-trip。

## 已知边界

T011 使用 Chat Completions JSON、非 streaming、非 tool-calling 的最小协议；默认
`RequestPromptBuilder` 只包含 request metadata，生产运行必须注入 FileContextStore 与
`StoredContextResolver`；InMemoryContextStore 仅适合单进程测试。
T011 不改变串行 runner 路由、Git、SQLite 或状态机，也不自动 merge/deploy。
