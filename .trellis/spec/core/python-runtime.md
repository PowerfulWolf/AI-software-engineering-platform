# Python Runtime Contract

## 1. Scope / Trigger

适用于控制平面的所有 Python 代码。新增领域模型、端口、adapter、CLI 命令、持久化或子进程执行功能时必须遵守。目标是用 Python 构建长期可维护的系统，而不是形成无边界脚本集合。

## 2. Signatures

核心端口以 `typing.Protocol` 表达：

```python
class AgentAdapter(Protocol):
    def run(self, request: AgentRequest) -> AgentResult: ...

class TaskRepository(Protocol):
    def get(self, task_id: TaskId) -> Task: ...
    def append_event(self, event: StateEvent) -> None: ...

class GitWorkspace(Protocol):
    def create(self, spec: WorktreeSpec) -> WorktreeRef: ...
    def inspect(self, revision: GitRevision) -> CandidateSnapshot: ...
```

CLI、数据库、Git、模型 SDK 和文件系统实现只能依赖这些端口，不得反向渗入领域层。

## 3. Contracts

- Python 版本：`>=3.12`，在 `pyproject.toml` 中声明；
- 外部 JSON/RPC/模型输出在 adapter 边界用 Pydantic 校验；
- 领域层使用明确类型、Enum、dataclass/Pydantic model，不传递裸 `dict[str, Any]`；
- `TaskStatus`、`AgentRole`、`ArtifactKind` 只有一个定义位置；
- 模型 SDK 只能存在于 `agents/adapters/` 或等价 infrastructure 层；
- subprocess 必须使用参数数组、timeout、明确 cwd 和环境 allowlist，不使用 `shell=True`；
- 依赖必须锁定；新增依赖要记录消除的 failure mode；
- JSON Schema 是跨语言 wire contract，Python model 必须有一致性测试。

## 4. Validation & Error Matrix

| 场景 | 校验位置 | 结果 |
|---|---|---|
| 模型返回非法 JSON | Agent adapter | 返回 typed invalid-output error，不进入领域层 |
| 未知 enum/status | Pydantic boundary | 拒绝输入，不使用默认分支吞掉 |
| 子进程超时 | command executor | 终止进程树并保存 timeout evidence |
| 未允许环境变量/secret | policy + executor | 不传入子进程，记录拒绝事件 |
| adapter 抛供应商异常 | adapter mapping | 转换为稳定的领域错误分类 |
| Python model 与 JSON Schema 漂移 | contract test | CI 失败，阻止发布 |

## 5. Good / Base / Bad Cases

- **Good**：领域服务只认识 `AgentAdapter` 和 typed result，真实模型与 fake adapter 可互换。
- **Base**：单机串行运行，无网络时 fake adapter 仍可完成状态机 e2e。
- **Bad**：CLI 直接调用模型 SDK、解析 dict、修改 SQLite 并迁移状态；必须拆分为入口、应用服务、端口和 adapter。

## 6. Tests Required

- Ruff 和严格类型检查通过；禁止新增未解释的 `Any`；
- Pydantic model 与 JSON Schema 双向 fixture 一致；
- 每个 adapter 有 success、invalid output、timeout、provider error 测试；
- subprocess 测试断言 argv/cwd/env/timeout 和 `shell=False`；
- fake adapter 与真实 adapter 共用 request/result contract；
- 状态 reducer 的每个 enum 分支有覆盖，未知值在入口拒绝。

## 7. Wrong vs Correct

### Wrong

```python
def run_agent(payload: dict) -> dict:
    return client.responses.create(**payload)
```

### Correct

```python
def run(self, request: AgentRequest) -> AgentResult:
    raw = self._client.invoke(self._encode(request))
    return AgentResult.model_validate(self._decode(raw))
```

前者让供应商对象和未类型化 payload 穿透系统；后者把不稳定输入封装在 adapter 边界。
