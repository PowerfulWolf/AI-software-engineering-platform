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

## 8. Scenario: Installable CLI Package

### 8.1 Scope / Trigger

新增或修改 Python 包结构、console script、根 CLI option、版本来源或构建后端时适用。CLI 是 delivery adapter，不能拥有领域状态或直接依赖基础设施实现。

### 8.2 Signatures

```text
console script: ase = ai_software_engineer.cli:main
ase --help     -> exit 0
ase --version  -> exit 0, stdout "ase <semantic-version>"
ase            -> exit 0, show root help
```

```python
def main() -> None: ...
```

### 8.3 Contracts

- 包路径固定为 `src/ai_software_engineer`；
- `pyproject.toml` 声明 Python `>=3.12`、console script 和锁定依赖；
- `src/ai_software_engineer/__about__.py` 是版本号唯一来源，构建元数据与 CLI 读取同一值；
- CLI 只解析输入和呈现输出，后续业务命令必须调用 typed application service；
- 需要随包分发的 prompt/resources 放在 `src/ai_software_engineer/` 内，不放在仓库根部的临时 runtime 目录。

### 8.4 Validation & Error Matrix

| 场景 | 预期结果 |
|---|---|
| `ase --help` | exit 0，展示产品说明和 options |
| `ase --version` | exit 0，输出安装包版本 |
| `ase` | exit 0，展示 help，不静默退出 |
| 未知 option | 非零退出并展示 usage error，不显示内部 traceback |
| metadata 与公开版本漂移 | contract test 失败 |

### 8.5 Good / Base / Bad Cases

- **Good**：安装后的 `ase` 可从任意目录运行，CLI 与包 metadata 版本一致。
- **Base**：Typer `CliRunner` 在进程内验证根命令，不需要网络或外部服务。
- **Bad**：在 CLI callback 中创建 SQLite、调用模型或推进 Task 状态。

### 8.6 Tests Required

- `importlib.metadata.version("ai-software-engineer") == __version__`；
- help、无参数、version 和未知 option 四个 CLI contract tests；
- `ruff format --check .`、`ruff check .`、strict mypy 和 pytest 全部通过；
- 构建 wheel 后可以安装并运行 `ase --help`（发布前门禁）。

### 8.7 Wrong vs Correct

#### Wrong

```python
@app.command()
def run() -> None:
    sqlite = connect("state.db")
    model = VendorClient()
    execute_task(sqlite, model)
```

#### Correct

```python
@app.command()
def run(task_id: str) -> None:
    service = build_run_task_service()
    result = service.run(TaskId(task_id))
    render_delivery_result(result)
```
