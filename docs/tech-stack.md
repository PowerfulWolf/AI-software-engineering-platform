# 技术选型与理由

> 状态：已接受。控制平面正式采用 Python 3.12+；完整决策、替代方案和演进边界见 [`decisions/0001-python-control-plane.md`](decisions/0001-python-control-plane.md)。

## 选型总表

| 领域 | v0.1 选择 | 理由 | 暂不选择 |
|---|---|---|---|
| 语言 | Python 3.12+ | CLI、JSON、Git、测试和模型 SDK 生态成熟，便于快速迭代 | 多语言微服务 |
| 契约 | Pydantic v2 + JSON Schema | 运行时校验与跨语言文件契约兼顾；Schema 可供非 Python 工具使用 | 手写 dict 校验 |
| CLI | Typer | 轻量、类型友好，适合 `task run/inspect/retry` | Web 控制台优先 |
| 状态存储 | MySQL 8.0（生产）+ SQLite（兼容/测试） | MySQL 提供 Task/事件/dispatch 行锁和跨进程恢复；SQLite 保留快速离线测试 | PostgreSQL、Redis |
| Artifact | JSON + 文件系统 | 可 diff、可签名、可被人工检查，避免锁定数据库格式 | 二进制消息总线 |
| 编排 | 进程内显式状态机 | 便于调试和回放，串行流程不需要队列 | Celery、Temporal、Kafka |
| Repo 隔离 | Git CLI + worktree | 原生支持分支、diff 和回滚，任何语言 Agent 都能复用 | 自研 VCS 抽象 |
| Prompt | 版本化 Markdown/Jinja2 模板 | 可评审、可追踪、便于把规则与任务数据分离 | 隐式 prompt 拼接 |
| Agent 接口 | typed `AgentAdapter` + Codex CLI/Responses/fallback | 当前 ChatGPT/Codex 登录可直接用 GPT-5.5；HTTP provider 可替换且共用 Schema/policy | 在 Orchestrator 中硬编码 SDK |
| 测试 | pytest + contract fixtures | 覆盖状态机、Schema、权限和端到端 happy path | 只做手工演示 |
| 可观测性 | Sidecar Evidence/Artifact + MySQL 状态 | 模型、命令、candidate、attempt 与状态可以重放，且不污染目标项目 | 先上完整 tracing 平台 |
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

实现应先写接口与 contract tests，再接入具体模型。T034 的生产入口默认通过 Codex CLI 使用当前
账号的 GPT-5.5，并提供 Responses-compatible HTTP adapter 给显式配置的 Qwen/DeepSeek fallback；两类
provider 都只能返回相同 typed output。transport、runner 与 PromptBuilder 均可注入，因此无网络或
模型配额时仍能用 scripted/fake adapter 完整验证状态机、MySQL、worktree 和 artifact 边界。

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

## Future TODO — PostgreSQL repository adapter

- `TaskRepository` Protocol、Task/StateEvent JSON 与 Artifact 契约已经让存储实现可替换；T034 的生产
  adapter 当前选择 MySQL 8.0，SQLite 只保留为离线/兼容后端；
- 如需 PostgreSQL，应增加独立 adapter，而不是修改领域模型或在业务层分支 SQL；
- 进入实施前新增 ADR，明确 MySQL→PostgreSQL 数据迁移、事务隔离、灾备、运维和成本，并运行同一套
  repository contract tests。
