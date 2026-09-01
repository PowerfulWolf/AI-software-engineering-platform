# Context Builder / Context Routing

## 1. 目标与边界

Context Builder 把组织规则、项目事实、Task 意图、角色说明和已声明的上游证据编译成一个最小、确定、可审计的 `ContextBundle`。它不做语义检索、不调用模型，也不接受 Agent 间隐式消息；只有显式声明的来源才会进入上下文。

v0.1 的本地实现是 `FileContextBuilder`，路由器是无 I/O 的 `ContextRouter`。Builder 绑定一个 role worktree root，并复用 T006 `WorkspacePolicy` 读取文件来源。应用层的 `FileRunContextBuilder` 根据 AgentDefinition 权限创建 Builder，并把 ArtifactStore 已读回的显式上游 Artifact 编译成 required `artifact://<artifact_id>` inline source；它不接受隐式 Agent 消息。T011 可为它注入 `ContextStore`，将返回的 manifest 先登记/持久化，再由真实 provider adapter 按 `context_manifest_id` 解析。

## 2. 公共接口

```python
class ContextRouter(Protocol):
    @staticmethod
    def route(sources: tuple[ContextSource, ...], role: AgentRole) -> tuple[ContextSource, ...]: ...


class ContextBuilder(Protocol):
    def build(
        self,
        task: Task,
        role: AgentRole,
        *,
        attempt: int,
        candidate_revision: str | None = None,
    ) -> ContextBundle: ...


class ContextStore(Protocol):
    def put(self, context: ContextBundle) -> ContextBundle: ...
    def get(self, context_id: ContextId) -> ContextBundle: ...
```

`InMemoryContextStore` 用于单进程测试；真实运行使用 `FileContextStore` 将 canonical
ContextBundle 以 `<context_id>.json` 原子落盘。Store 会重新计算排除 `built_at` 的 manifest
SHA-256；相同 identity 的重复登记返回首次观察值，不同内容复用 ID、文件篡改或非法 JSON
分别抛 `ContextConflict`/`ContextCorruption`，不会把不可信 manifest 交给模型。

`ContextSource` 必须且只能提供一个 `content: str` 或 `relative_path: str`；`roles=()` 表示所有角色，否则只匹配声明的 `AgentRole`。`priority=0` 保留给机器 policy，外部来源必须使用正数优先级。

`ContextBundle.to_wire()` 是 Agent adapter 的唯一输入 manifest，包含：`context_id`、`task_id`、`role`、`attempt`、精确 `source_revision`、带 `content/uri/sha256/tokens/priority/truncated` 的 `sections`、安全的 `redactions`、`budget` 和 UTC `built_at`。正式跨语言契约为 [`schemas/context.schema.json`](../schemas/context.schema.json)。

## 3. 来源层次与路由

| 来源 | Orchestrator | Coder | QA | Reviewer |
|---|---:|---:|---:|---:|
| 机器 policy（优先级 0） | ✓ | ✓ | ✓ | ✓ |
| 组织/项目规范（显式 source） | ✓ | ✓ | ✓ | ✓ |
| Task + acceptance（生成 section） | ✓ | ✓ | ✓ | ✓ |
| role instructions（生成 section） | ✓ | ✓ | ✓ | ✓ |
| candidate revision（提供时生成） | ✓ | ✓ | ✓ | ✓ |
| 上游 artifact/evidence（显式 source） | ✓ | 重试时 | ✓ | ✓ |
| Agent 隐式会话消息 | ✗ | ✗ | ✗ | ✗ |

Builder 始终生成并优先交付 `policy`、`task`、`role`；提供且不同于 `Task.base_ref` 的 candidate revision 时再生成 `candidate`。声明来源按 `(priority, uri, source_id)` 排序，因此调用方输入顺序不会影响结果。来源 ID 必须唯一，生成 ID (`policy/task/role/candidate`) 不能被外部 source 占用。

## 4. 构建算法与确定性

1. 校验 Task、role、`attempt ∈ [1, 10]` 和无控制字符的 `candidate_revision`；未提供 candidate 时使用 `Task.base_ref`。
2. 用 Task deny glob 和 role 的 `AgentPermissions` 创建绑定当前 worktree root 的 `WorkspacePolicy`。
3. 路由生成来源与显式来源；文件来源只能按 root-relative POSIX path 读取，直接 content 仍视为不可信数据。
4. 对 URI 和正文先执行脱敏，再计算 token 和 SHA-256。v0.1 token 估算固定为 `ceil(len(Python str)/4)`；section SHA-256 是脱敏正文的 lower-case digest。
5. 遵守 `max_input_tokens`：required section 放不下时抛 `ContextBudgetExceeded`；optional section 放不下时按稳定规则截断到剩余 token，剩余为 0 则省略。任何成功 bundle 的 `used_input_tokens` 都等于 section token 总和且不超上限。
6. 用 canonical JSON（UTF-8、排序 key、compact separators、禁止 NaN）对不含 `context_id` 与 `built_at` 的 manifest 求 SHA-256，生成 `ctx_<64 hex>`；随后附加 UTC `built_at`。
7. 只有 bundle 完整构建成功后才能启动 Agent；上下文 ID 必须写入后续 Agent request/artifact，支持重放和审计。

相同 Task、role、attempt、权限、来源正文、candidate revision 和 budget 必须产生相同 section 顺序、hash、token 计数和 `context_id`；`built_at` 仅是观察元数据，不参与身份哈希。

状态迁移后的 Task 快照属于 Context identity 的一部分：例如 planning run 的 Task section 是 `PLANNING`，Coder run 是 `IMPLEMENTING`。重放或离线 Fake scenario 必须使用对应 durable checkpoint 构建 manifest，不能拿 `NEW` 快照冒充后续输入。

## 5. 脱敏与注入边界

Builder 覆盖 OpenAI 风格 key、AWS access key、GitHub token、Bearer token、PEM private key，以及 `password/passwd/secret/token/api_key` assignment。替换值为 `[REDACTED:<kind>]`，只记录 `uri/kind/count`；当原始 URI 含 secret 时，审计 metadata 使用已脱敏的 `source://<source_id>`，不得泄露原 URI。

仓库文件、Task prose 和测试输出都按数据处理。恶意文本只能作为自己的 section content 出现，不能覆盖 `policy` section、改变 role/permissions、创建隐式 source 或驱动状态迁移。发现越权要求时由 Orchestrator 依据 policy 记录 evidence 或进入 `BLOCKED`。

## 6. 失败契约

| 输入/状态 | 稳定结果 |
|---|---|
| 重复/非法 source ID、role metadata/URI、外部 priority 0 | `ContextSourceError` |
| 缺失 required 文件 | `ContextSourceNotFound` |
| traversal、absolute、`.git`、symlink escape、deny 命中 | `ContextSourceDenied` |
| 非 UTF-8/不可读文件 | `ContextSourceError` |
| required section 超预算 | `ContextBudgetExceeded`，不返回 partial bundle |
| optional section 超预算 | 确定性截断或省略，不超预算 |
| candidate revision 含空白/控制字符 | `ContextSourceError` |

## 7. Good / Base / Bad

- **Good**：相同输入重复构建得到相同 `context_id`；QA 收到 exact candidate SHA 和 QA 专属 evidence；secret 在 hash/count 前已替换。
- **Base**：离线临时 worktree 只用 Markdown 和 inline evidence 构建 bundle，不需要 Git 网络、模型 SDK、向量库或数据库。
- **Bad**：把所有文件盲目拼接、让仓库指令排到 policy 前、在脱敏前计算 hash、把 Reviewer evidence 路由给 Coder，或 required source 放不下却静默返回 partial bundle。
