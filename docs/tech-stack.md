# 技术选型与理由

> 状态：已接受。控制平面正式采用 Python 3.12+；完整决策、替代方案和演进边界见 [`decisions/0001-python-control-plane.md`](decisions/0001-python-control-plane.md)。

## 选型总表

| 领域 | v0.1 选择 | 理由 | 暂不选择 |
|---|---|---|---|
| 语言 | Python 3.12+ | CLI、JSON、Git、测试和模型 SDK 生态成熟，便于快速迭代 | 多语言微服务 |
| 契约 | Pydantic v2 + JSON Schema | 运行时校验与跨语言文件契约兼顾；Schema 可供非 Python 工具使用 | 手写 dict 校验 |
| CLI | Typer | 轻量、类型友好，适合 `task run/inspect/retry` | Web 控制台优先 |
| 状态存储 | SQLite（WAL） | 单机事务、零运维，足够支撑 v0.1 审计 | PostgreSQL、Redis |
| Artifact | JSON + 文件系统 | 可 diff、可签名、可被人工检查，避免锁定数据库格式 | 二进制消息总线 |
| 编排 | 进程内显式状态机 | 便于调试和回放，串行流程不需要队列 | Celery、Temporal、Kafka |
| Repo 隔离 | Git CLI + worktree | 原生支持分支、diff 和回滚，任何语言 Agent 都能复用 | 自研 VCS 抽象 |
| Prompt | 版本化 Markdown/Jinja2 模板 | 可评审、可追踪、便于把规则与任务数据分离 | 隐式 prompt 拼接 |
| Agent 接口 | `AgentAdapter`（OpenAI-compatible 默认） | 模型供应商可替换，角色契约不绑定某家 API | 在 Orchestrator 中硬编码 SDK |
| 测试 | pytest + contract fixtures | 覆盖状态机、Schema、权限和端到端 happy path | 只做手工演示 |
| 可观测性 | 结构化 JSONL 日志 + SQLite metrics | 本地可用，易导出；保留 task/attempt/agent 关联 | 先上完整 tracing 平台 |
| 构建后端 | Hatchling | 配置小、支持 `src` layout 和单一版本来源，不侵入运行时 | 自定义构建脚本 |
| 打包 | `pyproject.toml` + uv/pip | 简洁、可重复安装 | 多模块容器平台 |

## 关键接口（实现阶段）

```python
class AgentAdapter(Protocol):
    def run(self, request: AgentRequest) -> AgentResult: ...


class ContextBuilder(Protocol):
    def build(
        self,
        task: Task,
        role: AgentRole,
        *,
        attempt: int,
        candidate_revision: str | None = None,
    ) -> ContextBundle: ...


class ArtifactStore(Protocol):
    def put(self, artifact: Artifact) -> ArtifactRef: ...
    def get(self, artifact_id: ArtifactId) -> Artifact: ...
```

实现应先写接口与 contract tests，再接入具体模型。这样可以用 fake adapter 在没有网络或模型配额时完整测试状态机。

## 选型原则

- 每引入一个依赖，都必须回答“它消除了哪个 v0.1 的真实 failure mode”；
- 运行时核心优先使用标准库和少量稳定依赖；
- 数据格式优先可读、可迁移、可回放；
- 替换模型不应改变 Task、Agent、Artifact 的 Schema；
- 任何异步/分布式组件都推迟到有基准数据证明单机串行不足之后。

## Python 的生产级约束

- 使用 `src` layout 或等价的明确包边界，不把核心逻辑堆在 CLI 文件；
- 公开函数、领域模型和跨层返回值必须有完整类型；禁止裸 `dict` 作为内部协议；
- Pydantic 负责外部数据入口校验，领域层不重复解析未类型化 payload；
- 状态机尽量保持纯函数，I/O 通过 Protocol 端口注入；
- 使用 Ruff、严格类型检查和 pytest；contract、权限、恢复测试属于发布门禁；
- 依赖必须锁定，模型 SDK 只能出现在 adapter 层；
- 性能优化必须由 profiling/metrics 驱动，不能以“未来可能需要”为由提前分布式化。

Python 不限制目标仓库语言。所有构建和测试通过受 policy 管理的命令执行，例如 Maven、Gradle、CMake、CTest、Go test、npm 或 pytest。

## Future TODO — 可扩展 Task Repository

- 保持 `TaskRepository` Protocol、Task/StateEvent JSON 和 Artifact 契约稳定；未来可将 SQLite 实现替换为 PostgreSQL 等服务端后端。
- 触发条件：真实并发、远程多用户协作、备份/高可用或单机 WAL 已无法满足指标，而不是“预想中的规模”。
- 进入实施前必须新增 ADR，明确迁移、事务隔离、灾备、运维和成本，并保留 SQLite 作为离线/fake adapter 测试后端。
