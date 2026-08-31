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

## SQLite Task Repository and State Events

### Scope / Trigger

新增或修改 Task 持久化、状态事件、SQLite schema、重启恢复或幂等写入时适用。Repository 是领域模型和 SQLite 之间的唯一边界；领域层不能导入 `sqlite3`。

### Signatures

```python
class TaskRepository(Protocol):
    def create(self, task: Task) -> None: ...
    def get(self, task_id: TaskId) -> Task: ...
    def append_event(self, event: StateEvent) -> None: ...
    def list_events(self, task_id: TaskId) -> tuple[StateEvent, ...]: ...
    def current_revision(self, task_id: TaskId) -> int: ...
```

Concrete implementation: `SqliteTaskRepository(database: str | Path)`.

### Contracts

- Task row stores typed `Task.to_wire()` JSON, indexed status/timestamps, and a non-negative per-Task revision; a new Task starts at revision 0;
- `append_event` executes `BEGIN IMMEDIATE`, checks exact event ID replay, compares `event.from_status` with the current typed Task, inserts the event at `revision + 1`, updates the Task snapshot, and commits once;
- identical event ID + identical JSON is a no-op; identical event ID + changed payload raises `EventIdempotencyConflict`;
- malformed persisted JSON raises `StoreCorruption`; missing Task raises `TaskNotFound`; duplicate Task ID raises `TaskAlreadyExists`; stale `from_status` raises `InvalidStateEvent`;
- SQLite connections set `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`, and `PRAGMA synchronous = NORMAL`;
- repository does not decide whether a status edge is legal; T004 state-machine guard owns that policy.

### Validation & Error Matrix

| 输入问题 | 检测点 | 结果 |
|---|---|---|
| Task ID already exists | `create` transaction | rollback + `TaskAlreadyExists` |
| Event Task does not exist | `append_event` | rollback + `TaskNotFound` |
| Event `from_status` differs from snapshot | append guard | rollback + `InvalidStateEvent` |
| Event ID replay with changed payload | idempotency check | rollback + `EventIdempotencyConflict` |
| Stored JSON or revision has invalid type | decode boundary | `StoreCorruption` |
| Process closes and reopens | durable snapshot/event rows | same Task/events/revision recovered |

### Good / Base / Bad Cases

- **Good**: append one valid event, reopen the database, and replay the same event without changing revision;
- **Base**: repository uses one local SQLite file, WAL, and no in-memory cache, so fake adapters can test recovery offline;
- **Bad**: update the Task row first and write an event later, overwrite an event ID, or accept a stale `from_status`.

### Tests Required

- `tests/store/test_repository.py` must assert create/get, close/reopen, atomic append, exact replay, conflicting replay, stale status rollback, unknown Task errors, and SQLite runtime pragmas;
- `tests/domain/test_event.py` must assert StateEvent schema, immutability, orchestrator ownership, and duplicate artifact rejection;
- contract fixtures must validate `StateEvent.to_wire()` against `schemas/state-event.schema.json` with format checking;
- repository tests must assert no event/revision mutation after every rejected operation.

### Wrong vs Correct

#### Wrong

```python
task = repository.get(task_id)
task.status = event.to_status
repository.save(task)
repository.append_event(event)
```

#### Correct

```python
repository.append_event(event)
assert repository.current_revision(event.task_id) == 1
```

前者产生没有事件证据的状态写入并留下部分提交风险；后者让 Task 快照和 StateEvent 在一个事务中前进。

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

## 9. Scenario: Typed Domain and Wire Contracts

### 9.1 Scope / Trigger

新增或修改 `Task`、`AgentDefinition`、Artifact envelope、四类 Artifact content、共同 Enum 或跨语言 JSON 字段时适用。Python model 是不可信输入进入领域层的第一道边界；`schemas/*.json` 仍是其他语言和外部工具使用的正式 wire contract。

### 9.2 Signatures

```python
Task.model_validate(payload: object) -> Task
AgentDefinition.model_validate(payload: object) -> AgentDefinition
validate_artifact(payload: object, kind: ArtifactKind) -> Artifact
DomainModel.to_wire() -> WirePayload
```

实现位置固定为：

```text
src/ai_software_engineer/domain/
├── enums.py
├── model.py
├── task.py
├── agent.py
└── artifact.py
```

### 9.3 Contracts

- model 使用 Pydantic v2、`extra="forbid"` 和 `frozen=True`；所有 optional wire property 在 `to_wire()` 中缺省时省略，不能输出 Schema 不接受的 `null`；
- `TaskStatus`、`AgentRole`、`ArtifactKind` 只在 `domain/enums.py` 定义；其他模块必须导入，不得复制字符串常量；
- `AgentDefinition` 每个 role 只拥有一种 output：`orchestrator → plan`、`coder → implementation-report`、`qa → qa-report`、`reviewer → review-report`；
- Artifact subtype 的 `kind`、typed `content` 和 `producer.role` 必须一致；
- Artifact content 引用的 Evidence ID 必须存在于同一 envelope，Evidence 必须有 URI 和 SHA-256；Finding 至少引用一个 Evidence ID；
- QA `PASS` 要求报告内 criterion/test 全为 `PASS` 且无 `MAJOR/BLOCKER`；Reviewer `APPROVE` 只允许 `INFO` finding，`REJECT` 至少包含一个 `MAJOR/BLOCKER`；
- 需要 Task、候选 revision 或历史 artifact 才能判断的规则不得塞入单对象 validator，应由后续 Orchestrator/ArtifactStore guard 校验。

### 9.4 Validation & Error Matrix

| 输入问题 | 检测点 | 结果 |
|---|---|---|
| 未知字段、非法 ID/Enum、naive timestamp | Pydantic model boundary | `ValidationError`，不进入 repository |
| Task attempt 超预算或两个 max-attempt 来源冲突 | `Task` after-validator | 拒绝 Task |
| role/output 或 producer/kind 不匹配 | `AgentDefinition` / Artifact subtype | policy-invalid，不能产出 verdict |
| content 引用不存在的 Evidence ID | Artifact subtype validator | artifact 无效 |
| QA/Review verdict 与 findings 冲突 | content after-validator | verdict 无效，要求同角色重跑 |
| Python wire payload 不符合 JSON Schema | `tests/contracts/test_json_schema_contracts.py` | CI 失败，阻止合并 |

### 9.5 Good / Base / Bad Cases

- **Good**：`validate_artifact` 按 `kind` 返回具体 subtype，`to_wire()` 可通过对应 Draft 2020-12 Schema；
- **Base**：可选字段缺失时不写出 `null`，时间统一为带时区的 RFC 3339 字符串；
- **Bad**：Coder 伪造 `qa-report`、Review `APPROVE` 同时携带 `MAJOR` finding，或测试引用 envelope 中不存在的 Evidence。

### 9.6 Tests Required

- `tests/domain/`：合法、非法、边界和同对象不变量；
- `tests/contracts/test_json_schema_contracts.py`：Task、Agent 和四类 Artifact 的正例必须同时通过 Python model 与 canonical Schema；
- Schema 反例至少覆盖非法 ID、未知字段、缺失 typed content、缺 Evidence SHA 和非法 date-time；
- producer-role/output-kind、Evidence link、QA status 和 Review verdict 必须有独立断言；
- Ruff、strict mypy 和完整 pytest 必须同时通过。

### 9.7 Wrong vs Correct

#### Wrong

```python
role = payload.get("role", "coder")
if payload["content"].get("verdict") == "APPROVE":
    advance_task(payload)
```

#### Correct

```python
artifact = validate_artifact(payload, ArtifactKind.REVIEW_REPORT)
if isinstance(artifact, ReviewReportArtifact):
    deliver_review(artifact)
```

前者让默认值、裸字典和自报 verdict 穿透边界；后者先完成类型、角色、Evidence 和 verdict 一致性校验。
