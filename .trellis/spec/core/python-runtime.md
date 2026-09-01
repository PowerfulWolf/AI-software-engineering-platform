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
    def inspect(self, worktree: WorktreeRef) -> WorktreeSnapshot: ...
    def remove(self, worktree: WorktreeRef) -> None: ...


class WorkspacePolicy:
    def __init__(
        self,
        workspace_root: str | Path,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None: ...
    def authorize_read(self, path: str | PurePosixPath) -> PurePosixPath: ...
    def authorize_write(self, path: str | PurePosixPath) -> PurePosixPath: ...
    def authorize_command(self, arguments: tuple[str, ...]) -> tuple[str, ...]: ...
```

CLI、数据库、Git、模型 SDK 和文件系统实现只能依赖这些端口，不得反向渗入领域层。

## 3. Contracts

- Python 版本：`>=3.12`，在 `pyproject.toml` 中声明；
- CLI 只做参数、错误和 JSON 编排；Task、Evaluation 和 Handoff 规则必须委托给 typed
  application services 与 ports。成功命令输出 canonical JSON，错误输出稳定单行 stderr 和非零退出码；
- `task create` 不得通过导入已完成或已有 attempt 的快照绕过 `NEW → PLANNING`；
- `evaluation report` 只能从 `TaskRepository`、`ArtifactStore` 和 `EvaluationEventStore` 重算，
  禁止把一个不可回放的 `adr=true` 当作事实；
- `handoff build` 只能读取 `DONE/BLOCKED`，并将 immutable store 返回的路径作为结果；CLI 不执行
  review argv、merge 或修改终态记录；
- 外部 JSON/RPC/模型输出在 adapter 边界用 Pydantic 校验；
- 领域层使用明确类型、Enum、dataclass/Pydantic model，不传递裸 `dict[str, Any]`；
- `TaskStatus`、`AgentRole`、`ArtifactKind` 只有一个定义位置；
- 模型 SDK 只能存在于 `agents/adapters/` 或等价 infrastructure 层；
- subprocess 必须使用参数数组、timeout、明确 cwd 和环境 allowlist，不使用 `shell=True`；
- Git adapter 必须禁用 repository hooks/fsmonitor，拒绝 repository-local external checkout filters，并用 `--no-ext-diff --no-textconv` 检查变更；
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
    def record_attempt(self, task_id: TaskId, attempt: int) -> None: ...
    def list_events(self, task_id: TaskId) -> tuple[StateEvent, ...]: ...
    def current_revision(self, task_id: TaskId) -> int: ...
```

Concrete implementation: `SqliteTaskRepository(database: str | Path)`.

### Contracts

- Task row stores typed `Task.to_wire()` JSON, indexed status/timestamps, and a non-negative per-Task revision; a new Task starts at revision 0;
- `append_event` executes `BEGIN IMMEDIATE`, checks exact event ID replay, compares `event.from_status` with the current typed Task, inserts the event at `revision + 1`, updates the Task snapshot, and commits once;
- `record_attempt` executes an atomic snapshot update without adding a state event; it is idempotent for
  the same/lower attempt and rejects values above `Task.max_attempts`;
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

## Task State Machine Guard and Reducer

### Scope / Trigger

新增状态迁移、Orchestrator 路由或 StateEvent 回放时适用。状态图只能在 `orchestration/state_machine.py` 定义一次；该模块是纯函数，不得导入 SQLite、Git、Agent SDK 或执行 subprocess。

### Signatures

```python
validate_transition(task: Task, to_status: TaskStatus) -> None
build_event(task: Task, to_status: TaskStatus, *, event_id: EventId,
            reason: str, source_revision: str,
            artifact_ids: tuple[ArtifactId, ...] = (),
            attempt: int = 1,
            occurred_at: datetime) -> StateEvent
apply_event(task: Task, event: StateEvent) -> Task
```

### Contracts

- `NEW -> PLANNING -> IMPLEMENTING -> QA -> REVIEW -> DONE` 是主路径；QA/Review 的 retry、BLOCKED 和非终态到 FAILED 是唯一额外边；
- `DONE`、`BLOCKED`、`FAILED` 为终态，自迁移和终态迁移拒绝；
- `build_event` 固定 `actor=orchestrator`，必须先通过 `validate_transition`；
- StateEvent 的 `attempt`（1..10）用于审计；Agent 调用前必须由 repository checkpoint 同一
  attempt，重启时取快照与事件最大值恢复预算；
- `apply_event` 检查 Task ID、`from_status`、合法边和 `occurred_at >= task.updated_at`，返回 `model_copy`，不得修改输入；
- repository 只持久化事件，不重复实现状态图；Artifact verdict、candidate revision 和 attempt budget 属于后续跨对象 guard。

### Validation & Error Matrix

| 输入问题 | 检测点 | 结果 |
|---|---|---|
| 未定义边或自迁移 | `validate_transition` | `IllegalTransition` |
| Task 已处于终态 | `validate_transition` | `TerminalTask` |
| Event Task ID 不匹配 | `apply_event` | `TaskMismatch` |
| Event 起始状态落后 | `apply_event` | `StaleEvent` |
| Event 时间早于快照 | `apply_event` | `StaleEvent` |

### Good / Base / Bad Cases

- **Good**：`build_event` 生成 orchestrator-owned StateEvent，`apply_event` 返回新快照，原 Task 保持不变；
- **Base**：调用方使用 fake artifact metadata，纯 reducer 仍可离线测试完整状态图；
- **Bad**：直接写 `task.status`、绕过 guard，或让 repository 接受跳过 QA/Review 的事件。

### Tests Required

- 每条合法边、每个终态、自迁移和代表性跳转错误都有断言；
- 生成事件通过 StateEvent Pydantic 与 JSON Schema contract；
- Task ID、from_status、时间戳错误返回 typed error 且原快照不变；
- reducer 测试禁止 I/O/import side effect，严格 mypy 和 Ruff 必须通过。

## Immutable Filesystem ArtifactStore

### Scope / Trigger

新增或修改 Artifact 持久化、摘要、parent/supersedes lineage 或读取恢复时适用。`artifacts/` 包是 typed Artifact 与文件系统之间的唯一边界；Agent 和 domain model 不直接读写 artifact 文件。

### Signatures

```python
class ArtifactStore(Protocol):
    def put(self, artifact: Artifact) -> ArtifactRef: ...
    def get(self, artifact_id: ArtifactId) -> Artifact: ...
    def list_for_task(self, task_id: TaskId) -> tuple[Artifact, ...]: ...

artifact_digest(artifact: Artifact) -> Sha256
seal_artifact(artifact: Artifact, *, validated_at: datetime) -> Artifact
FileArtifactStore(root: str | Path)
```

### Contracts

- canonical digest 使用 `artifact.to_wire()`、排序 key、compact separators、UTF-8、`allow_nan=false`，并排除顶层 `integrity`；
- `seal_artifact` 返回新 Artifact，不修改输入；`put` 要求 `schema_version=v0.1`、typed validation、`validated=true` 和 digest 匹配；
- 文件名只来自已校验的 Artifact ID，布局为 `<root>/<artifact-id>.json`；
- exact ID + exact wire payload 是幂等 no-op；相同 ID 的不同正文抛 `ArtifactAlreadyExists`；
- 所有 parent/supersedes 必须已存在且同 Task；supersedes 还必须同 kind；
- 写入顺序为同目录 temporary file → flush → `fsync` → `os.replace`；失败清理临时文件，不产生正式文件；
- `get` 必须重新执行 typed validation、schema version 和 digest 校验，不能返回裸 dict。
- `list_for_task` 必须逐个执行同样的校验，并按稳定顺序返回指定 Task 的可信 Artifact；
  损坏文件 fail closed，不能被恢复逻辑忽略。

### Validation & Error Matrix

| 输入/持久化问题 | 结果 |
|---|---|
| Artifact ID 不存在 | `ArtifactNotFound` |
| unsealed 或 digest mismatch | `ArtifactIntegrityError`（put）/`ArtifactCorruption`（get） |
| unsupported schema version | `SchemaVersionError`（put）/`ArtifactCorruption`（get） |
| missing/cross-Task parent | `ArtifactParentError` |
| supersedes 不同 kind | `ArtifactParentError` |
| existing ID changed payload | `ArtifactAlreadyExists` |
| JSON 截断、ID mismatch、typed validation failure | `ArtifactCorruption` |
| NaN/Infinity 等非标准 JSON 数值 | `ArtifactValidationError` |

### Good / Base / Bad Cases

- **Good**：seal plan，put/get round-trip，随后实现报告引用该 plan 作为 parent；
- **Base**：相同 sealed Artifact 重放时返回同一 ref，不重写文件；
- **Bad**：让 Agent 自报 digest、覆盖旧 artifact、接受缺失 parent，或直接 `write_text` 到正式文件。

### Tests Required

- seal/digest deterministic、immutable input、put/get 和 ref 测试；
- unsealed、digest mismatch、schema version、missing/cross-Task/cross-kind lineage 测试；
- exact replay 与 immutable conflict 测试；
- corrupted/truncated/tampered file 和 successful-write temp cleanup 测试；
- 完整 JSON Schema contract suite、Ruff、strict mypy 和 build 必须通过。

### Wrong vs Correct

#### Wrong

```python
path.write_text(json.dumps(agent_payload))
```

#### Correct

```python
sealed = seal_artifact(artifact, validated_at=now)
reference = artifact_store.put(sealed)
assert artifact_store.get(reference.artifact_id) == sealed
```

前者让 Agent 自报内容和摘要并可覆盖历史证据；后者在 typed boundary 重新校验、验证 digest/lineage，并通过原子文件写入保持不可变。

## Isolated Git Worktree and Workspace Policy

### 1. Scope / Trigger

新增或修改 Git worktree、候选 revision 检查、role workspace 清理、路径/命令授权或任何 Git subprocess 时适用。`src/ai_software_engineer/git/` 是 Orchestrator 与本地 Git CLI 之间的唯一 seam；Agent 不得提交任意 Git 字符串给该 adapter。

### 2. Signatures

```python
class GitWorkspace(Protocol):
    def create(self, spec: WorktreeSpec) -> WorktreeRef: ...
    def inspect(self, worktree: WorktreeRef) -> WorktreeSnapshot: ...
    def remove(self, worktree: WorktreeRef) -> None: ...


GitWorktreeManager(repository: str | Path, worktree_root: str | Path,
                   *, command_timeout_seconds: float = 30.0)


WorkspacePolicy(workspace_root: str | Path,
                permissions: AgentPermissions,
                *, denied_paths: tuple[str, ...] = ())

WorkspacePolicy.authorize_read(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_write(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_command(arguments: tuple[str, ...]) -> tuple[str, ...]
```

`WorktreeSpec` 字段固定为 `task_id`、`role`、`attempt`、`source_revision`；`WorktreeRef` 固定返回 role layout、完整 HEAD SHA、branch 或 detached 标志；`WorktreeSnapshot` 返回当前完整 HEAD SHA 和已排序的 staged/unstaged/untracked relative paths。

### 3. Contracts

- worktree root 必须位于 main checkout 之外，layout 固定为 `<root>/<task-id>/<role>-attempt-<NN>`；create 在落盘前解析 target 的已有 symlink parents，结果必须仍位于 configured root 内；
- Coder 创建 `ai/<task-id>/attempt-<n>` branch，QA/Reviewer detached 到同一 candidate commit；Orchestrator role 不允许构造 `WorktreeSpec`；
- source ref 必须先通过 `git rev-parse --verify --end-of-options <ref>^{commit}` 固化为完整 SHA；已有 target 或 Coder branch 不复用；
- `inspect/remove` 只接受 layout 和 Git common directory 都与 manager 匹配的 `WorktreeRef`；
- `remove` 先检查 staged、unstaged 和 untracked paths，dirty worktree 抛 `DirtyWorktree(changed_paths)` 并保留现场，clean cleanup 不删除 branch/commit；
- Git subprocess 只使用 argv、`shell=False`、固定 timeout、明确 cwd 和最小 env；每次 invocation 覆盖 `core.hooksPath=/dev/null`、`core.fsmonitor=false`；
- repository-local `filter.*.(clean|smudge|process)` 可能在 checkout 运行外部程序，v0.1 在 create 前以 `UnsafeRepositoryConfiguration` fail closed；diff inspection 传 `--no-ext-diff --no-textconv`；
- `WorkspacePolicy` 必须绑定实际 role worktree root。路径先做 POSIX lexical validation，再解析已有 symlink parents 并验证仍在 root 内且不指向 `.git`；deny glob 优先于 role read/write allowlist；
- command allowlist entry 用 `shlex.split` 解析成完整 token prefix。运行时只接受预先 tokenized argv；空命令、shell 控制 token、换行、`$()`、backtick 或未匹配 prefix 都拒绝；
- path/command policy 是 application guard，不替代未来的 OS/container sandbox、network isolation、resource limit 和 command-argument-specific controls。

### 4. Validation & Error Matrix

| 输入/状态 | 结果 |
|---|---|
| repository 不存在、不是 Git root 或传入子目录 | `InvalidRepository` |
| worktree root 位于 main checkout 内，或 task target 经 symlink 逃逸 root | `InvalidWorktreeRoot`，不创建目录 |
| source ref 不存在/不是 commit | `RevisionNotFound` |
| repository-local external checkout filter | `UnsafeRepositoryConfiguration`，不执行 filter |
| target path 或 Coder branch 已存在 | `WorktreeAlreadyExists`，不复用旧现场 |
| ref path/layout/common Git directory 不匹配 | `UnmanagedWorktree` |
| cleanup 前有 tracked/untracked change | `DirtyWorktree.changed_paths`，保留 worktree |
| Git non-zero/timeout | `GitCommandError` / `GitCommandTimeout` |
| workspace root 不存在、absolute/traversal/`.git`/symlink escape/deny path | `PathPolicyViolation` |
| argv/allowlist 为空、含 shell syntax 或 prefix 不匹配 | `CommandPolicyViolation` |

### 5. Good / Base / Bad Cases

- **Good**：Coder 在独立 branch 形成 candidate；QA/Reviewer detached 到同一 SHA；inspection 返回相同 HEAD；clean worktree 可回收且 candidate branch 保留。
- **Base**：无网络的临时 Git repository 创建一个 role worktree，main HEAD/branch/status 完全不变。
- **Bad**：把 worktree root 放进 main checkout、允许 `../secret` 或 symlink escape、把 `git push` 错配成 `git diff`、执行 repository hook/filter，或 force-remove dirty worktree。

### 6. Tests Required

- 真实 temporary Git fixture 断言 Coder branch、QA/Reviewer detached SHA、目录隔离和 main checkout 不变；
- inspection 同时断言 staged、unstaged、untracked path；cleanup 断言 dirty preserve、clean remove、branch retain；
- 反例覆盖 invalid role/repository/root/revision、symlinked task directory escape、target/branch collision 和 forged ref；
- policy 覆盖 read/write separation、deny precedence、absolute/`..`/`.git`、symlink escape、empty Reviewer writes、command token prefix collision 和 shell-like argv；
- executable `post-checkout` hook 的 sentinel 必须不生成；external smudge/process filter 必须在执行前被拒绝；
- Ruff、strict mypy、完整 pytest、lock、build 和 `git diff --check` 全部通过。

### 7. Wrong vs Correct

#### Wrong

```python
subprocess.run(agent_command, cwd=main_checkout, shell=True)
shutil.rmtree(worktree_path, ignore_errors=True)
```

#### Correct

```python
worktree = git_workspace.create(spec)
policy = WorkspacePolicy(worktree.path, permissions, denied_paths=task_denied_paths)
safe_path = policy.authorize_write("src/package/service.py")
safe_argv = policy.authorize_command(("pytest", "tests/unit", "-q"))

snapshot = git_workspace.inspect(worktree)
if snapshot.dirty:
    persist_changed_path_evidence(snapshot.changed_paths)
else:
    git_workspace.remove(worktree)
```

前者把 prompt、main checkout 和 destructive cleanup 组合成不可审计执行；后者只通过 typed seam、绑定 root 的 policy 和 dirty guard 推进。

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

## 10. Scenario: Deterministic Context Builder and Router

### 10.1 Scope / Trigger

新增或修改 Agent context、prompt 输入 manifest、组织/项目来源、secret redaction、token budget 或 role routing 时适用。`src/ai_software_engineer/context/` 是 Knowledge Plane 到 Agent adapter 的唯一 seam；Builder 不调用模型、不读取未声明文件、不接受 Agent 间隐式消息。

### 10.2 Signatures

```python
class ContextRouter(Protocol):
    @staticmethod
    def route(
        sources: tuple[ContextSource, ...], role: AgentRole
    ) -> tuple[ContextSource, ...]: ...


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


FileContextBuilder(
    project_root: str | Path,
    permissions: AgentPermissions,
    *,
    sources: tuple[ContextSource, ...] = (),
    budget: ContextBudget = ContextBudget(
        max_input_tokens=12_000, reserved_output_tokens=4_000
    ),
) -> None
```

`ContextSource` 是 `source_id`、`uri`、二选一的 `content/relative_path`、`roles`、`priority`、`required`；`ContextBundle` 固定包含 `context_id`、`task_id`、`role`、`attempt`、`source_revision`、`sections`、`redactions`、`budget` 和 `built_at`。`ContextSection` 包含脱敏 `content`、`uri`、`sha256`、`tokens`、`priority`、`truncated`。

### 10.3 Contracts

- 生成 section `policy`、`task`、`role` 固定存在且分别使用优先级 0、30、40；candidate revision 不同于 `Task.base_ref` 时生成优先级 50 的 `candidate`。外部 source 的 priority 0 保留并拒绝；来源 ID 必须唯一。
- `roles=()` 路由到所有角色；否则只有匹配 role 才进入。最终顺序固定为 `(priority, uri, source_id)`，不得依赖输入 tuple 顺序。
- file source 只接受 root-relative path，并通过绑定 worktree root 的 `WorkspacePolicy.authorize_read` 读取；direct content 仍先脱敏。`candidate_revision` 原样成为 `source_revision`，不由 Builder 解析或替换。
- 脱敏发生在 token 计数、SHA-256 和 wire 输出之前；API key、AWS/GitHub/Bearer token、PEM private key 和 password/secret/token/api_key assignment 只留下 `ContextRedaction(uri, kind, count)`，原值和原始 secret URI 不得进入 payload。
- optional section 超出剩余 `max_input_tokens` 时按稳定字符截断，剩余为 0 则省略；required section 放不下抛错，不生成 partial bundle。`used_input_tokens == sum(section.tokens)`。
- `context_id = "ctx_" + sha256(canonical_json(manifest_without_context_id_and_built_at))`；canonical JSON 使用 UTF-8、排序 key、compact separators、`allow_nan=False`。`built_at` 是 UTC 观察元数据，不参与 identity。
- 仓库/Task/命令输出均是 data；其文本不能改变 policy、权限、role 路由、source 声明或状态迁移。ContextBundle 成功构建后才可启动 Agent，并把 ID 写入 AgentRequest/artifact。
- `FileRunContextBuilder` 接受 optional ContextStore；真实 provider 运行必须注入 store，并以
  store 返回的首次观察 manifest 作为 request identity。`FileContextStore` 使用临时文件、
  `fsync`、原子 rename 和 read-back canonical ID 校验；相同 identity 重放不覆盖 built_at，
  不同内容复用 ID 或文件篡改分别返回 `ContextConflict`/`ContextCorruption`。

### 10.4 Validation & Error Matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| 重复 source ID、保留 priority 0、非法 role/source shape/URI control chars | model/router/builder | `ContextSourceError` |
| required 文件缺失 | root-bound reader | `ContextSourceNotFound` |
| absolute、`..`、`.git`、deny 或 symlink escape | `WorkspacePolicy` | `ContextSourceDenied`，不读文件 |
| 文件不可读或非 UTF-8 | reader | `ContextSourceError` |
| required section 超过 max input | budget compiler | `ContextBudgetExceeded`，无 partial bundle |
| optional section 超预算 | budget compiler | 确定性截断/省略，成功 bundle 不超额 |
| candidate revision 含空白/控制字符 | revision validator | `ContextSourceError` |
| secret pattern 命中 | redactor | 替换 + safe `ContextRedaction`，不失败 |

### 10.5 Good / Base / Bad Cases

- **Good**：同一 Task/role/attempt、权限、来源和 candidate SHA 重复构建得到相同 ID、顺序、hash、tokens；QA/Reviewer 只收到其 role 允许的 evidence。
- **Base**：临时 worktree + inline Markdown source 在无网络、无模型、无向量库时完成 bundle 构建并通过 Schema。
- **Bad**：在脱敏前 hash/count、把所有仓库文件拼入 context、让恶意 source 使用 priority 0 覆盖 policy、把 Reviewer source 路由到 Coder，或 required overflow 静默返回半包。

### 10.6 Tests Required

- `tests/context/test_router.py`：all-role/role-specific filtering、duplicate ID、priority/URI/source stable ordering 和 priority 0 rejection。
- `tests/context/test_builder.py`：重复构建 identity/order/hash/tokens、candidate propagation、真实 `WorkspacePolicy` traversal/deny/`.git`/symlink/missing、secret URI/content redaction、optional truncate/omit、required overflow、prompt-injection data boundary。
- `tests/context/test_store.py`：内存/文件 Store round-trip、built_at 等价重放、canonical ID
  冲突、非法 lookup ID、持久化篡改和 unknown manifest。
- `tests/orchestration/test_context_registry.py`：FileRunContextBuilder 返回值与登记 manifest 完全一致。
- `tests/contracts/test_json_schema_contracts.py`：ContextBundle 正例与缺失 section hash/sections 反例必须校验 [`schemas/context.schema.json`](../../schemas/context.schema.json)。
- Ruff、strict mypy、完整 pytest、`uv lock --check`、`uv build` 和 `git diff --check` 是合并门禁。

### 10.7 Wrong vs Correct

#### Wrong

```python
prompt = "\n".join(Path(path).read_text() for path in repository_files)
tokens = estimate(prompt)
digest = sha256(prompt.encode())
```

#### Correct

```python
bundle = context_builder.build(
    task,
    AgentRole.QA,
    attempt=1,
    candidate_revision=candidate_sha,
)
request = AgentRequest(
    task_id=task.id,
    context_manifest_id=bundle.context_id,
    source_revision=bundle.source_revision,
)
```

前者绕过 role routing、root policy、脱敏和可重放 manifest；后者只把验证过的 ContextBundle 通过 typed seam 交给 Agent adapter。

## 11. Scenario: Typed Agent Adapter and Deterministic Fake

### 11.1 Scope / Trigger

新增或修改 Agent request/response、模型 provider adapter、timeout/failure mapping、run replay 或 FakeAgentAdapter 场景时适用。`src/ai_software_engineer/agents/` 是 Orchestrator 与模型执行器之间的唯一 seam；真实 SDK、网络和 prompt 渲染不得进入 domain 或 Fake adapter。

### 11.2 Signatures

```python
class AgentAdapter(Protocol):
    def run(self, request: AgentRequest) -> AgentResult: ...


class FakeAgentAdapter:
    def __init__(
        self,
        *,
        scenarios: Mapping[tuple[AgentRole, int], FakeScenario] | None = None,
        default: FakeScenario | None = None,
    ) -> None: ...
    def run(self, request: AgentRequest) -> AgentResult: ...
```

`AgentRequest` 固定字段为 `run_id`、`task_id`、`role`、`attempt`、`source_revision`、`context_manifest_id`、`input_artifact_ids`、`permissions`、`output_schema` 和 `timeout_seconds`。`AgentResult` 固定回显身份字段，并包含 `status`、可选 `artifact`、可选 `error` 和 `duration_ms`。`AgentFailure` 固定为 `code`、`message`、`transient`。

### 11.3 Contracts

- 所有 request/result/scenario model 使用 Pydantic v2、`extra="forbid"`、`frozen=True`；`run_id`、`context_manifest_id`、Task/Artifact ID 和 attempt 采用既有 typed aliases。
- `AgentRequest.output_schema` 固定映射：Orchestrator → `schemas/plan.schema.json`、Coder → `schemas/implementation-report.schema.json`、QA → `schemas/qa-report.schema.json`、Reviewer → `schemas/review-report.schema.json`；角色/Schema 不匹配在 adapter 启动前拒绝。
- `AgentResult.SUCCEEDED` 必须有且只有一个 typed Artifact，且 Artifact 的 `task_id`、producer role/run ID、kind 和 context manifest ID 与 request 完全一致。Orchestrator/QA/Reviewer Artifact revision 必须与 request 相同；Coder Artifact 可以是新 candidate，但必须满足 `source_revision == content.commit_sha`。成功的 QA 只能是 `PASS`，成功的 Reviewer 只能是 `APPROVE`。
- `FAILED`/`TIMED_OUT` 必须没有 Artifact；必须有 `AgentFailure`。`TIMED_OUT` 只能使用 `TIMEOUT` code；`INVALID_OUTPUT` 不产生 verdict，`PROVIDER_ERROR` 可标记 transient 供后续 retry router 使用。
- `FakeBehavior` 支持 `SUCCESS`、`QA_FAIL`、`REVIEW_REJECT`、`TIMEOUT`、`INVALID_OUTPUT`、`PROVIDER_ERROR`。QA_FAIL 只能由 QA role 产生 FAIL report，REVIEW_REJECT 只能由 Reviewer 产生 REJECT report；行为与 role 不匹配是配置错误。
- Fake scenario 按 `(role, attempt)` 选择，default 作为兜底；缺少 scenario、非法 key 或 attempt 越界抛 `AgentConfigurationError`，不得猜测默认行为。
- 同一 `run_id` 的完全相同 AgentRequest 重放返回相同 immutable AgentResult；相同 ID 搭配任一不同 request 字段抛 `AgentRequestConflict`，不重复执行 scenario。
- Fake adapter 不访问网络、Git、文件系统或模型 SDK。真实 adapter 必须复用同一 Protocol 和 typed result，不得把 provider response 或裸 dict 穿透到 Orchestrator。

### 11.4 Validation & Error Matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| request 缺字段、非法 ID/role/attempt/权限 | Pydantic boundary | `ValidationError`，不执行 |
| scenario 缺失、key/attempt 非法、特殊行为 role 不匹配 | Fake configuration | `AgentConfigurationError` |
| artifact task/role/run/kind/context mismatch | adapter output guard | `FAILED + INVALID_OUTPUT`，无 artifact |
| Coder candidate 与 implementation `commit_sha` 不同 | adapter output guard | `FAILED + INVALID_OUTPUT`，无 artifact |
| 非 Coder artifact revision 与 request 不同 | adapter output guard | `FAILED + INVALID_OUTPUT`，无 artifact |
| QA 成功非 PASS 或 QA_FAIL 非 FAIL | adapter output guard | `FAILED + INVALID_OUTPUT` |
| Reviewer 成功非 APPROVE 或 REJECT 非 REJECT | adapter output guard | `FAILED + INVALID_OUTPUT` |
| provider/invalid output scenario | adapter mapping | `FAILED + typed code`，无 verdict |
| timeout scenario | adapter mapping | `TIMED_OUT + TIMEOUT(transient=true)`，无 artifact |
| same run ID + exact request | replay cache | 原结果幂等返回 |
| same run ID + changed request | replay cache | `AgentRequestConflict`，不覆盖原结果 |

### 11.5 Good / Base / Bad Cases

- **Good**：Fake adapter 为 Coder 从 request 的输入基线返回自洽的新 candidate implementation-report；QA FAIL 和 Reviewer REJECT 只由对应 role 返回；timeout 不产生 Artifact。
- **Base**：无网络的 fixture 测试通过 scenario script 复现成功、失败和重试输入，真实 adapter 可替换而无需修改 Orchestrator。
- **Bad**：让 Coder 返回 `qa-report`、让 Coder candidate 与报告 `commit_sha` 不同、让 QA/Reviewer 审查不同 SHA、把 timeout 当 PASS、对同一 run ID 重新执行，或让 Fake 直接调用供应商 SDK。

### 11.6 Tests Required

- `tests/agents/test_fake.py`：四类 role success、QA FAIL、Review REJECT、timeout、invalid/provider failures、scenario routing、missing/invalid config、artifact identity/verdict mismatch、run replay/conflict 和 result state invariants。
- 测试使用现有 typed Artifact factory 的 identity-aligned copies，通过 `AgentAdapter.run` 公共 seam 断言，不 mock Pydantic validator、缓存或内部 helper。
- 每个 failure 断言 `status/code/transient`、无 artifact、无 verdict；每个 success 断言 artifact producer/kind/task/source/context/run 对齐。
- Ruff、strict mypy、完整 pytest、`uv lock --check`、`uv build` 和 `git diff --check` 是合并门禁。

### 11.7 Wrong vs Correct

#### Wrong

```python
raw = model.invoke(prompt)
if raw.get("status") == "PASS":
    return raw
```

#### Correct

```python
result = agent_adapter.run(request)
if result.status is AgentRunStatus.SUCCEEDED:
    artifact = result.artifact
    assert artifact is not None
    if result.role is AgentRole.CODER:
        assert artifact.source_revision == artifact.content.commit_sha
    else:
        assert artifact.source_revision == request.source_revision
```

前者让 provider dict 和自报 verdict 穿透边界；后者只接受与 request 身份对齐的 typed Artifact，失败和超时不会被误当成交付信号。

## 12. Scenario: Serial Orchestrator Happy Path

### 12.1 Scope / Trigger

新增或修改应用层 Task 执行、跨 Artifact gate、role Context composition、Agent Run identity、
checkpoint 或交付结果时适用。`orchestration/runner.py` 是 v0.1 Control Plane 应用服务；它编排
端口但不拥有 SQLite、文件系统、Git 或模型 SDK 实现。

### 12.2 Signatures

```python
class RunContextBuilder(Protocol):
    def build(
        self,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle: ...


class OrchestrationIdentityFactory(Protocol):
    def new_run_id(self, task_id: TaskId, role: AgentRole, attempt: int) -> RunId: ...
    def new_event_id(
        self,
        task_id: TaskId,
        from_status: TaskStatus,
        to_status: TaskStatus,
        attempt: int,
    ) -> EventId: ...


class SerialOrchestrator:
    def run_task(self, task_id: TaskId) -> DeliveryResult: ...


class RetryingOrchestrator:
    def run_task(self, task_id: TaskId) -> DeliveryResult | BlockedResult: ...
```

`DeliveryResult` 固定包含最终 typed Task、candidate revision、四个 Artifact ID、四个 Context
manifest ID、四个 run ID 和五个 event ID。默认 identity factory 使用 UUID；测试通过 Protocol
注入确定值，clock 也通过 callable 注入。

### 12.3 Contracts

- runner 只接受 `NEW` Task，T009 固定 attempt=1，顺序为 planning-mode Orchestrator →
  Coder → QA → Reviewer；不能并行、跳步或在本阶段自行重试；
- T010 `RetryingOrchestrator` 从 durable `PLANNING`/`IMPLEMENTING`/`QA`/`REVIEW` checkpoint
  恢复，在 `Task.max_attempts` 内重试当前 role 或回流 Coder；不引入 DAG、队列或向量库；
- 状态 checkpoint 固定为 5 个事件：`PLANNING`、`IMPLEMENTING`、`QA`、`REVIEW`、`DONE`；
  所有事件通过 `build_event` + `TaskRepository.append_event` 提交，再从 repository 读回快照；
- 每次 run 先用当前 durable Task 快照构建 Context。Task status/updated_at 在 Task section 中，
  因此 `NEW`、`PLANNING` 等快照不能互换而保持同一 context ID；
- `FileRunContextBuilder` 使用 AgentDefinition permissions 创建 `FileContextBuilder`，只把显式
  `input_artifacts` 编译成 canonical JSON `artifact://<id>` required source，并验证 Task、kind、ID；
- 输出 Artifact 必须回显 request identity；direct parent 固定为 plan `()`、implementation
  `(plan)`、QA `(implementation)`、review `(qa)`；producer run IDs 必须各不相同；
- plan/implementation/QA criterion IDs 必须与 Task acceptance criteria 精确集合相等；QA
  必须 PASS、Reviewer 必须 APPROVE；QA/Review 必须绑定 implementation candidate；
- runner 重新 seal Agent Artifact，再通过 ArtifactStore put/get，只有读回的 Artifact 才进入
  下游 Context；`DONE` event 引用完整四 Artifact 链；
- QA FAIL、Review REJECT 和 Agent failure 不直接进入下阶段。T010 将 finding 作为已持久化
  Artifact 路由到新 Coder attempt，或在预算/策略失败时返回 `BlockedResult`。

### 12.4 Validation & Error Matrix

| 输入/状态 | 结果 | durable checkpoint |
|---|---|---|
| Task 非 NEW | `TaskNotRunnable` | 不变，0 个新增事件 |
| roles 缺失、key/definition role 不同、agent ID 重复 | `OrchestratorConfigurationError` | 不启动 |
| Agent FAILED/TIMED_OUT | `AgentRunFailed(result)` | 当前 stage |
| QA FAIL / Review REJECT | `UnexpectedVerdict` | QA / REVIEW；verdict Artifact 已持久化 |
| context/request/result identity 不同 | `DeliveryContractViolation` 或 typed adapter error | 当前 stage |
| criterion set、parent lineage、candidate、run uniqueness 错误 | `DeliveryContractViolation` | 不推进下一 stage |
| Artifact seal/store/read-back 失败 | typed ArtifactStore error | 当前 stage |
| event/repository 失败 | typed state/repository error | 最近已提交 checkpoint |

### 12.5 Good / Base / Bad Cases

- **Good**：fixture Task 到 DONE；SQLite revision=5；四 Artifact lineage/run/context 可复核；
  数据库关闭重开后仍能读取相同 DONE Task 与事件流。
- **Base**：无 Git、网络、模型 SDK时，FakeAgentAdapter + 临时 SQLite/filesystem 完成离线闭环。
- **Bad**：直接把 Agent 自由文本转成状态；把未持久化 Artifact 拼进下游 prompt；用 `NEW`
  Task 预建所有 Context；在 QA FAIL 后继续 REVIEW；复用同一个 run ID 伪装独立审查。

### 12.6 Tests Required

- `tests/orchestration/test_runner.py` happy path 通过 public `run_task` seam，使用真实
  `SqliteTaskRepository`、`FileArtifactStore`、`FileRunContextBuilder` 和 Fake adapter；
- 断言最终 DONE/candidate、5 个有序事件、repository revision=5、四 Artifact sealed/lineage、
  四个 Context ID、四个独立 run ID，以及关闭重开后的 Task/event；
- 反例至少覆盖 Agent timeout、QA FAIL、plan criterion 缺失、重复 run ID、非 NEW Task；
  每例断言具体 typed error、当前 Task status/revision 和未产生的下游 Artifact；
- Ruff、strict mypy、完整 pytest、lock、build 和 `git diff --check` 全部通过。

### 12.7 Wrong vs Correct

#### Wrong

```python
text = agent.run(prompt)
if "PASS" in text:
    task.status = TaskStatus.DONE
```

#### Correct

```python
result = runner.run_task(task.id)
assert result.task.status is TaskStatus.DONE
assert len(result.artifact_ids) == 4
assert len(result.run_ids) == 4
assert repository.current_revision(task.id) == 5
```

前者绕过 Context、ArtifactStore、独立 verdict 和事件事务；后者只从可重放的 typed 证据链
得到交付结果。

## 13. OpenAI-compatible AgentAdapter

### Scope / Trigger

接入真实模型 provider、HTTP transport、prompt 编译、响应 JSON 解码或 provider 错误映射时
适用。实现固定在 `src/ai_software_engineer/agents/openai_compatible.py`，不得把供应商
SDK 类型带入 domain、store 或 orchestration。

### Signatures

```python
class PromptBuilder(Protocol):
    def build(self, request: AgentRequest) -> PromptPayload: ...


class HttpTransport(Protocol):
    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse: ...


OpenAICompatibleAgentAdapter.run(request: AgentRequest) -> AgentResult
```

### Contracts

- endpoint 只能是 `http`/`https` URL，规范化为 `/chat/completions`；URL 不得携带 userinfo；
- body 固定使用 JSON `model`、policy-first `messages`、`temperature=0`、`stream=false` 和
  `response_format={"type":"json_object"}`；API key 只进入 Authorization header；
- `RequestPromptBuilder` 只发送 request metadata；生产运行注入 `ContextPromptBuilder`，通过
  `StoredContextResolver(ContextStore, ArtifactStore)` 读取已持久化 ContextBundle 和 input Artifact；policy 置于 system，
  其余仓库/Task 文本均是 user data；
- 2xx response 只接受完整 v0.1 Artifact JSON，可移除单层 Markdown JSON fence；调用
  `validate_artifact`，再由 `AgentResult` 检查 task/role/run/kind/context/source revision；
- provider producer agent identity 由 adapter 绑定当前配置，Orchestrator 随后负责 sealing；
  adapter 不写 ArtifactStore、不推进 Task、不执行 Git；
- HTTP 408/429/5xx 和连接错误为 transient `PROVIDER_ERROR`，其他 4xx 为 non-transient；
  timeout 为 `TIMED_OUT/TIMEOUT`；非法 JSON/Schema/identity 为 `INVALID_OUTPUT`；失败无 Artifact；
- adapter 内存 replay cache 以完整 `AgentRequest` 比较 request identity；相同 run 重放不发
  HTTP，冲突抛 `AgentRequestConflict`；错误消息不得包含 Authorization key 或 provider body。

### Tests Required

- fake transport 断言 URL、headers、timeout、JSON body 和 response format；
- 2xx direct/fenced/Responses JSON、HTTP 4xx/408/429/5xx、连接错误和 timeout 映射；
- Artifact role/kind/task/run/context/Coder candidate mismatch 拒绝且无 verdict；
- replay exact/conflict、endpoint validation、ContextPromptBuilder policy-first 与 cross-Task
  Artifact 拒绝；
- Ruff、strict mypy、完整 pytest、`uv lock --check`、`uv build` 和 `git diff --check` 必须通过。

## 14. Scenario: Replayable Evaluation and Human Handoff

### 14.1 Scope / Trigger

新增或修改 delivery metrics、ADR、Agent run instrumentation、人类动作、回归观察、终态交付包
或其文件持久化时适用。`src/ai_software_engineer/evaluation/` 是唯一边界；Evaluation 不修改
Task 状态，Handoff 不执行 Git/merge。

### 14.2 Signatures

```python
class EvaluationEventStore(Protocol):
    def append(self, event: EvaluationEvent) -> EvaluationEvent: ...
    def get(self, event_id: EvaluationEventId) -> EvaluationEvent: ...
    def find(self, event_id: EvaluationEventId) -> EvaluationEvent | None: ...
    def list_for_case(self, case_id: EvaluationCaseId) -> tuple[EvaluationEvent, ...]: ...


class EvaluatingAgentAdapter:
    def run(self, request: AgentRequest) -> AgentResult: ...


class EvaluationTraceBuilder:
    def build(self, case_id: EvaluationCaseId) -> EvaluationTrace: ...


class EvaluationEngine:
    def evaluate(self, traces: tuple[EvaluationTrace, ...]) -> EvaluationReport: ...


class HandoffBuilder:
    def build(self, task_id: TaskId) -> HandoffBundle: ...


class FileHandoffStore:
    def put(self, bundle: HandoffBundle) -> HandoffRef: ...
    def get(self, handoff_id: HandoffId) -> HandoffBundle: ...
```

### 14.3 Contracts

- EvaluationEvent 是 `case_started | agent_run | human_action | regression_check` typed union；
  case/event/Task identity 必须一致，事件按 `(occurred_at, event_id)` 稳定排序；
- `FileEvaluationEventStore` 的磁盘 record 是 `{event, sha256}`；digest 基于 canonical event JSON，
  同 ID 同正文 replay 幂等，同 ID 改正文拒绝，读取重新验证 digest 与 Pydantic；
- `EvaluatingAgentAdapter` 只装饰现有 AgentAdapter。事件 ID 是 case/run 的 deterministic SHA-256；
  replay 读取首次 event timestamp 后重建同一事实，不重复调用 metrics counter；
- `EvaluationTraceBuilder` 要求唯一 CaseStartedEvent，并从 TaskRepository、ArtifactStore、
  EvaluationEventStore 读回所有事实；base/task/event/artifact identity 任一不同 fail closed；
- `EvaluationEngine` 不 I/O。ADR 状态固定 `ELIGIBLE/INELIGIBLE/PENDING/EXCLUDED`；Rate 保存
  numerator/denominator/value，分母 0 时 value 为 None；
- DONE chain 由最终 StateEvent 的四个 artifact ID 解析；plan base、implementation candidate、
  QA/Review revision/parent/verdict、criteria set、producer run uniqueness 和 integrity 全部匹配；
- disqualifying human actions、policy override、uncaught policy violation、回归 FAIL 使 ADR
  INELIGIBLE；只有回归观察缺失且其他条件合格时为 PENDING；
- `HandoffBuilder` 只接受 DONE/BLOCKED。DONE 使用同一个 delivery-chain resolver；BLOCKED 保留
  最后 reason、已有 candidate/findings/evidence；review commands 是 argv tuple；
- `handoff_id = handoff_ + sha256(canonical bundle excluding handoff_id/generated_at)`；Store 写
  `<id>.json` 与 `<id>.md`，两者用临时文件、fsync、atomic replace，读取必须互相一致。

### 14.4 Validation & Error Matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| case 无 start / 多 start | TraceBuilder | `EvaluationTraceNotFound` / `EvaluationTraceConflict` |
| case base、Task、event 或 artifact identity 不同 | TraceBuilder | `EvaluationTraceContractError` |
| event exact replay / changed replay | EventStore | 原事件 / `EvaluationEventConflict` |
| event JSON/digest/ID 被篡改 | FileEvaluationEventStore | `EvaluationEventCorruption` |
| same run replay | EvaluatingAgentAdapter | 原 result + 单个首次观察 event |
| run event 与 artifact producer 不同 | EvaluationEngine | ADR `INELIGIBLE: INCOMPLETE_RUN_EVIDENCE` |
| DONE 缺 regression check | EvaluationEngine | ADR `PENDING: REGRESSION_PENDING` |
| human 改码/测试/verdict/evidence 或 override | EvaluationEngine | ADR `INELIGIBLE` + stable reason |
| 非 DONE/BLOCKED 请求 handoff | HandoffBuilder | `HandoffNotReady` |
| DONE 缺有效四制品链 | HandoffBuilder | `HandoffContractError` |
| Handoff ID forged、JSON/Markdown 被改 | FileHandoffStore | integrity/corruption error |

### 14.5 Good / Base / Bad Cases

- **Good**：5 个 case 的事件/Artifact 重新装配后，completion/validity/evidence/ADR 的 numerator、
  denominator、value 与首次运行完全相同；DONE handoff 可直接展示 candidate/evidence/argv。
- **Base**：完整 DONE 但观察窗口未结束，handoff 仍可审阅，ADR 明确 PENDING。
- **Bad**：将 `DONE` 当 `adr=true`，从当前文件系统猜“无人修改”，保存无法重算的百分比，或让
  handoff 自动执行 Git merge。

### 14.6 Tests Required

- `tests/evaluation/test_event_store.py`：memory/file round-trip、order、exact replay、conflict、
  invalid lookup 和合法字段篡改；
- `tests/evaluation/test_emitter.py`：valid output、invalid output、exact replay 单事件/首次时间；
- `tests/evaluation/test_trace.py`：真实 SQLite + sealed FileArtifactStore + FileEvaluationEventStore
  组装 eligible trace，并覆盖 missing start/base mismatch；
- `tests/evaluation/test_metrics.py`：eligible、pending、human + uncaught policy、blocked、regression
  与 invalid artifact output；固定 5-case ADR/completion 计数；
- `tests/evaluation/test_handoff.py`：DONE/BLOCKED 字段、非终态、断链、first observation 与
  Markdown 篡改；
- `tests/contracts/test_json_schema_contracts.py`：四类 Evaluation event/Handoff 正例和未知 action/
  空 next-actions 反例；Ruff、strict mypy、完整 pytest、lock、build、diff check 全部通过。

### 14.7 Wrong vs Correct

#### Wrong

```python
if repository.get(task_id).status is TaskStatus.DONE:
    metrics.save({"adr": True})
```

#### Correct

```python
trace = trace_builder.build(case_id)
report = EvaluationEngine().evaluate((trace,))
bundle = handoff_store.put(handoff_builder.build(trace.task.id))
assert report.summary.autonomous_delivery_rate.denominator == 1
assert bundle.handoff_id.startswith("handoff_")
```

前者丢失人工/policy/regression/invalid-output 事实且无法重算；后者只从 typed durable facts 得出
结论，并把人类交付与自动状态迁移分离。

## 15. T014 Runtime Configuration and Task Run Composition

### 15.1 Scope / Trigger

新增或修改 `ase task run`、provider endpoint 配置、API key 环境变量、角色模型覆盖、
Runtime store 路径或 Evaluation case 启动时适用。Runtime 是 operator-owned composition
root，不能成为绕过既有 typed ports、状态机或 ArtifactStore 的第二套业务实现。

### 15.2 Signatures

```python
RuntimeConfig.from_file(path: str | Path) -> RuntimeConfig
RuntimeConfig.agent_definitions() -> dict[AgentRole, AgentDefinition]
RoleAwareAgentAdapter(adapters: Mapping[AgentRole, AgentAdapter])
RoleAwareAgentAdapter.run(request: AgentRequest) -> AgentResult
RuntimeSession(config: RuntimeConfig, *, environment: Mapping[str, str] | None = None,
               agent_adapter: AgentAdapter | None = None)
RuntimeSession.run_task(task_id: TaskId, *, case_id: EvaluationCaseId | None = None) -> RuntimeRunResult
```

Runtime 配置 JSON 的必填字段是 `endpoint` 和 `model`；`api_key_env` 只能是大写环境变量
名。`paths` 固定包含 `database`、`artifacts`、`contexts`、`evaluation_events` 和
`handoffs`。`role_overrides` 每个 `AgentRole` 最多一项。

### 15.3 Contracts

- API key 不属于 RuntimeConfig wire payload；RuntimeSession 只读取 `api_key_env` 指定的
  进程环境变量，异常消息只允许暴露变量名，不能暴露值或 provider response body。
- `RuntimeConfig.agent_definitions()` 必须生成恰好四个角色定义，并保持 T002 role input/output
  artifact mapping；默认 Coder 写 `src/**`/`tests/**`，QA 写 `tests/**`，Reviewer 不写，
  只有 Orchestrator 的 `can_change_state=true`，所有角色 `can_merge=false`。
- RuntimeSession 只打开已有 `SqliteTaskRepository`、`FileArtifactStore`、`FileContextStore`
  和 `FileEvaluationEventStore`，通过 `FileRunContextBuilder`、`EvaluatingAgentAdapter` 和
  `RetryingOrchestrator` 运行；不能在 Runtime 层直接设置 `Task.status` 或 sealing Artifact。
- 每次运行先写一条确定性 `CaseStartedEvent`（case ID、Task、base revision、model、prompt、
  spec 和 test entrypoints）；完全相同的 start 是幂等 no-op，不同 Task/base 的同 case 必须拒绝。
- 未提供 `case_id` 时使用 Task ID 的 SHA-256 前 32 位生成 stable `case_<hex>`；start event ID
  使用 case ID 的 SHA-256 前 32 位生成 `evalevt_case_started_<hex>`，满足 EvaluationEventId
  长度上限。
- 真实 provider 和离线 fake 只能通过同一 typed `AgentAdapter` 注入；T014 不新增 DAG、队列、
  vector store、自动 merge 或 deploy。

### 15.4 Validation & Error Matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| `api_key` 或其他未知 Runtime 字段 | Pydantic/JSON Schema boundary | 拒绝配置，不启动 Agent |
| `api_key_required=true` 且环境变量缺失 | RuntimeSession constructor | `RuntimeConfigurationError`，不打开运行 |
| endpoint 含控制字符、role 重复或 entrypoint 重复 | RuntimeConfig validator | 配置验证失败 |
| role override 写入路径超出角色边界 | `RuntimeConfig.agent_definitions()` | `RuntimeConfigurationError`，不启动 Agent |
| RoleAwareAgentAdapter 缺角色 | adapter composition | `RuntimeConfigurationError` |
| 同 case 的 Task/base/model/prompt/spec/tests 不一致 | CaseStarted guard | fail closed，不追加 start |
| case 已有 AgentRun/Human facts 但没有 CaseStarted | CaseStarted guard | fail closed，不补造 start |
| Task 为 DONE/BLOCKED/FAILED | RuntimeSession.run_task | `TaskNotRunnable`，不追加状态 |
| provider timeout/invalid output/policy failure | existing AgentAdapter + retry runner | typed AgentFailure，按 T010 分类重试或 BLOCKED |
| 同一 fake adapter 与真实 adapter request contract 不一致 | `AgentResult`/Artifact guard | 不产生 verdict，不迁移状态 |

### 15.5 Good / Base / Bad Cases

- **Good**：用 JSON 配置 endpoint/model，API key 在环境变量，注入 fake adapter 跑完四个角色；
  重启同一 case 不重复 CaseStartedEvent，所有 run/artifact/context 可从 stores 重放。
- **Base**：仅配置默认 role definitions，RuntimeSession 组合既有 T010 runner；provider 更换
  只替换 `AgentAdapter`，不改 domain 或 orchestration。
- **Bad**：把 key 写进 JSON、CLI 直接调用模型 SDK、Runtime 直接改 Task 为 DONE，或让 role
  override 授予 Reviewer 写生产代码/merge；这些都必须在 boundary fail closed。

### 15.6 Tests Required

- RuntimeConfig 正例通过 Pydantic 和 `schemas/runtime-config.schema.json`；未知字段、明文 key、
  非法 env name、重复 role/entrypoint 和越权 write path 均拒绝。
- `agent_definitions()` 断言四角色集合、输入/输出 Artifact、Coder/QA/Reviewer 写权限、
  Orchestrator state 权限和所有角色禁止 merge。
- RoleAwareAgentAdapter 断言按 request.role 路由并拒绝缺角色；RuntimeSession 断言缺 key、
  terminal Task、case identity mismatch 的稳定错误。
- fake adapter e2e 断言 `NEW → PLANNING → IMPLEMENTING → QA → REVIEW → DONE`、四个 Agent
  run、一个 CaseStartedEvent、immutable Artifact/Context 持久化和可重算 Evaluation trace。
- CLI 断言 `task run` 使用配置 paths、错误退出码为 2、不打印 traceback/API key；运行全量
  contract tests、Ruff、strict mypy、build 和 `git diff --check`。

### 15.7 Wrong vs Correct

#### Wrong

```python
payload = json.loads(Path("runtime.json").read_text())
client = OpenAI(api_key=payload["api_key"])
task.status = "DONE"
```

#### Correct

```python
config = RuntimeConfig.from_file(path)
with RuntimeSession(config) as runtime:
    result = runtime.run_task(task_id, case_id=case_id)
```

前者泄露 secret、绕过 typed adapter 和状态守卫；后者把配置、凭据、case 事实和串行路由
固定在可验证的 application composition seam。

## 16. T015 Policy-Bound Command Execution

### 16.1 Scope / Trigger

新增或修改 QA/Coder/Reviewer 命令执行、测试日志采集、worktree cwd、子进程超时或环境变量
传递时适用。`SubprocessCommandExecutor` 是执行命令的唯一预留端口；它不解释业务 verdict，
不写 Task/Artifact/Evaluation，也不替代未来的 OS/container sandbox。

### 16.2 Signatures

```python
class CommandExecutor(Protocol):
    def run(self, arguments: tuple[str, ...], *,
            timeout_seconds: float | None = None) -> CommandResult: ...


@dataclass(frozen=True, slots=True)
class CommandExecutorSettings:
    environment_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_ALL")
    default_timeout_seconds: float = 600.0
    max_output_bytes: int = 1_000_000


SubprocessCommandExecutor(
    workspace_root: str | Path,
    permissions: AgentPermissions,
    *,
    denied_paths: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
    environment_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_ALL"),
    default_timeout_seconds: float = 600.0,
    max_output_bytes: int = 1_000_000,
)

SubprocessCommandExecutor.run(arguments: tuple[str, ...], *,
                              timeout_seconds: float | None = None) -> CommandResult
```

`CommandResult` 固定包含 `argv`、`cwd`、`returncode`、`stdout`、`stderr`、`duration_ms`、
`stdout_truncated` 和 `stderr_truncated`。错误类型为 `CommandExecutionError` 和
`CommandTimedOut`；命令未授权沿用 `WorkspacePolicy` 的 `CommandPolicyViolation`。

### 16.3 Contracts

- `run` 只接受已 tokenized argv，调用前必须复用 `WorkspacePolicy.authorize_command`；不接受
  shell 字符串、shell 控制 token 或用户拼接的命令片段。
- cwd 永远是构造器绑定的 resolved worktree root；构造器要求该目录存在，不能由每次调用
  的参数覆盖或越过 `.git`/root containment。
- subprocess 固定 `shell=False`、`stdin=DEVNULL`、明确 cwd、`start_new_session=True`、
  timeout 和最小环境；timeout 先终止进程组，必要时升级为 SIGKILL，再抛 `CommandTimedOut`。
- 默认环境只含 `PATH`、`LANG=C`、`LC_ALL=C`；其他变量必须同时存在于注入映射和显式
  `environment_allowlist`，不复制完整 `os.environ`，不自动传递 API key/token/password。
- stdout/stderr 以 UTF-8 replacement 解码并分别限制 `max_output_bytes`；结果保留截断标志。
  非零 return code 仍是 typed `CommandResult`，必须由上层结合测试语义生成 evidence，不能
  直接写成 PASS。
- 仅“无法启动”和 timeout 抛 executor error；拒绝、非零退出和截断输出必须保留可观察事实。
  错误消息不能包含命令完整 argv 中可能出现的 secret 或输出正文。

### 16.4 Validation & Error Matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| workspace root 缺失/不是目录 | `WorkspacePolicy` constructor | `PathPolicyViolation`，不启动进程 |
| 未授权 command、空 argv 或 shell token | `authorize_command` | `CommandPolicyViolation` |
| allowlist 环境名重复/含小写、控制字符 | executor constructor | `ValueError` |
| timeout 非正数、NaN、Infinity | constructor/run | `ValueError` |
| max output bytes 非正数 | constructor | `ValueError` |
| executable 无法启动 | `Popen` | `CommandExecutionError`，不伪造结果 |
| process 超时 | `communicate`/process-group guard | `CommandTimedOut`，进程组已终止 |
| command exit code != 0 | result boundary | `CommandResult(returncode!=0)`，不产生 PASS |
| stdout/stderr 超限 | bounded decoder | `CommandResult` + 对应 truncated=true |
| 宿主环境含 secret 但未在 allowlist | env builder | secret 不进入子进程 |

### 16.5 Good / Base / Bad Cases

- **Good**：QA 在绑定 worktree 运行 `(sys.executable, "-c", "...")`，拿到 cwd、returncode、
  截断日志和 duration，再由 QA artifact 引用 evidence。
- **Base**：临时 fixture 只依赖 Python 标准库；允许 fake executor/fixture subprocess 替换真实
  进程，但两者都实现同一 `CommandExecutor` Protocol。
- **Bad**：`shell=True`、`"pytest " + user_input`、把完整 `os.environ` 传给 Agent、用
  `returncode == 0` 直接迁移 Task，或在 timeout 后保留仍运行的子进程。

### 16.6 Tests Required

- `tests/execution/test_executor.py`：成功、非零退出、stdout/stderr 截断、固定 cwd、timeout
  进程组终止、启动失败、未授权 argv、shell token、环境 secret 隔离和显式 allowlist。
- 断言每次 subprocess 的 `shell=False`、`stdin=DEVNULL`、`cwd`、`env`、`timeout` 和
  `start_new_session`；错误消息不包含 stdout、stderr 或 secret。
- 构造器边界测试覆盖缺失 root、非法 timeout、非法 output limit 和重复/非法环境名。
- 后续 Runtime/QA 集成必须断言非零结果被转换为 evidence 而非 verdict；完整 pytest、Ruff、
  strict mypy、build、lock 和 `git diff --check` 必须通过。

### 16.7 Wrong vs Correct

#### Wrong

```python
subprocess.run("pytest " + user_input, shell=True, env=os.environ)
```

#### Correct

```python
result = executor.run(("pytest", "-q"), timeout_seconds=120)
evidence = save_command_evidence(result)
```

前者允许 shell 注入、cwd/secret 越界并丢失 timeout 语义；后者在 policy、环境、资源和输出
边界内返回可审计事实，是否 PASS 仍由独立 QA 契约决定。

## 17. T016 Role Worktree Execution Composition

### 17.1 Scope / Trigger

新增或修改 role worktree 创建、Agent permissions 绑定、命令 executor 生命周期、dirty cleanup
或 candidate detached checkout 时适用。`RoleWorktreeSession` 是 T006 `GitWorkspace` 与
T015 `CommandExecutor` 之间的唯一组合端口；它不改变 Task/Artifact wire Schema，也不替代
未来的 OS/container sandbox。

### 17.2 Signatures

```python
@dataclass(frozen=True, slots=True)
class RoleWorktreeBinding:
    worktree: WorktreeRef
    executor: CommandExecutor

RoleWorktreeSession(
    git_workspace: GitWorkspace,
    *,
    environment: Mapping[str, str] | None = None,
    environment_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_ALL"),
    default_timeout_seconds: float = 600.0,
    max_output_bytes: int = 1_000_000,
)

RoleWorktreeSession.open(
    spec: WorktreeSpec,
    agent: AgentDefinition,
    *,
    denied_paths: tuple[str, ...] = (),
) -> RoleWorktreeBinding
RoleWorktreeSession.inspect(binding: RoleWorktreeBinding) -> WorktreeSnapshot
RoleWorktreeSession.close(binding: RoleWorktreeBinding) -> None
```

### 17.3 Contracts

- `open` 先检查 `spec.role is agent.role`，再调用注入的 `GitWorkspace.create`；
  `WorktreeSpec` 已拒绝 orchestrator，因此 orchestrator 没有 role worktree；
- 返回的 `WorktreeRef.path` 是唯一 executor cwd；session 不接受调用方另传的 cwd，也不从
  Agent prompt 解析路径；executor 继续执行 T015 的 argv、env、timeout、输出和 shell guards；
- Coder 的 branch、QA/Reviewer 的 detached candidate 和 attempt 编号完全由 GitWorkspace
  决定；session 不创建第二套 layout、branch 或 revision；
- `close` 只调用 `GitWorkspace.remove`。dirty worktree 必须抛出 `DirtyWorktree` 并保留现场，
  clean worktree 才能删除；删除不会删除 Coder branch 或 candidate commit；
- `RoleWorktreeSession` 构造器先创建并验证 T015 `CommandExecutorSettings`，非法环境名、timeout
  或 output limit 在任何 Git worktree/branch 创建前拒绝；若 path-bound executor 在 `open` 后仍
  意外初始化失败，仅对本次刚创建的 worktree 尝试受保护清理，原始错误继续抛出，清理失败通过
  exception note 暴露，不能静默吞掉；已有 binding 或 dirty worktree 不自动清理；
- session 只组合生命周期，不迁移 Task 状态、不落盘 Artifact、不解释 returncode/verdict，也
  不把模型自由文本变成命令。上层必须将 `CommandResult` 转成 evidence 并由独立 QA/Reviewer
  契约作决定。

### 17.4 Validation & Error Matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| spec.role 与 agent.role 不一致 | `RoleWorktreeSession.open` | `RoleWorktreeAgentMismatch`，不创建 worktree |
| spec.role 为 orchestrator | `WorktreeSpec` validator | `ValidationError`，不创建 worktree |
| Git repository/ref/root/layout 非法 | `GitWorkspace.create` | T006 typed Git error，binding 不产生 |
| executor env/timeout/output 配置非法 | `RoleWorktreeSession` / `CommandExecutorSettings` constructor | 稳定 `ValueError`，不创建 worktree/branch |
| 命令未授权或 shell token | binding.executor / `WorkspacePolicy` | `CommandPolicyViolation`，进程不启动 |
| 命令超时/启动失败 | T015 executor | `CommandTimedOut`/`CommandExecutionError` |
| binding worktree dirty | `RoleWorktreeSession.close` → GitWorkspace | `DirtyWorktree.changed_paths`，保留现场 |
| binding worktree clean | `RoleWorktreeSession.close` → GitWorkspace | 安全移除，branch/commit 保留 |

### 17.5 Good / Base / Bad

- **Good**：同角色 Coder binding 在 manager branch 中执行 allowlisted argv；QA binding detached
  到同一 candidate SHA；命令结果含 binding cwd，清理前先检查 snapshot；
- **Base**：真实临时 Git repository + Python 标准库命令即可覆盖组合层，无 provider、网络或
  数据库依赖；
- **Bad**：把 QA AgentDefinition 传给 Coder spec、把 main checkout 直接绑定 executor、
  忽略 `DirtyWorktree` 强制删除，或把模型输出 shell 字符串交给 binding。

### 17.6 Tests Required

- `tests/role_workspace/test_role_workspace.py` 覆盖 Coder cwd/branch、QA detached candidate、
  role mismatch、dirty cleanup/现场保留、clean cleanup 和 executor 初始化失败清理；
- 断言所有 binding 命令仍经 T015 `CommandExecutor`，不新增第二套 subprocess 或 Git 命令
  拼接路径；
- 运行全量 pytest、Ruff、strict mypy、build、lock 和 `git diff --check`。

### 17.7 Wrong vs Correct

#### Wrong

```python
subprocess.run(agent_text, shell=True, cwd=repository)
shutil.rmtree(worktree.path)
```

#### Correct

```python
binding = session.open(spec, agent_definition)
result = binding.executor.run(("pytest", "-q"))
snapshot = session.inspect(binding)
if not snapshot.dirty:
    session.close(binding)
```

前者绕过 role policy、shell/env/timeout 和 dirty evidence；后者把 worktree 所有权、命令执行和
清理边界固定在可验证的 typed seams。

## 18. T018 Organization Workforce Models

### 18.1 Scope and files

`src/ai_software_engineer/domain/workforce.py` 是组织 Agent、调度视图、Lease 和 run-scoped model
allocation 的唯一 Python 领域入口；正式 wire contract 是 `schemas/workforce.schema.json`。
共同 Enum 位于 `domain/enums.py`，不得在 Scheduler、Runtime 或 UI 重复定义。

### 18.2 Contracts

- 所有 model 继承 frozen/extra-forbid `DomainModel`，ID 使用 typed regex，时间必须带时区；
- AgentProfile 声明 capabilities、eligible_roles、max_parallel_assignments 和 default ModelPolicy；
  不允许 concrete model/project permissions；
- ModelPolicy 的 provider/model route 必须唯一，完整覆盖四个 RiskTier，default/floor BrainTier
  必须有 route；ModelSelection 至少一个 machine-readable reason；
- RunDemand 只携带可观测的 role/risk、上下文规模、计划变更规模、受影响层和失败计数，供后续
  ModelRouter 做 deterministic selection；不得把具体模型固化到 AgentProfile；
- waiting WorkItem 必须有 wait_reason；RETRY_SCHEDULED 还必须有 future available_at；非 waiting
  WorkItem 不得携带 wait_reason；
- TaskLease expires_at 必须晚于 acquired_at；`lease_is_active` 显式接收 clock，不读取全局时间；
- RoleAssignment/AgentRunAllocation attempt 从 1 开始；run allocation 必须携带完整归因；
- `validate_assignment_independence` 拒绝同一 Task 历史中同 Agent 跨 Coder/QA/Reviewer 角色；
- ProjectWorkspace `schema_version=v0.1/layout_version=v0.2`，固定 `assignments/` 替换 `agents/`；
  legacy manifest fail closed，不自动删除或迁移。

### 18.3 Tests and quality gates

- `tests/workforce/test_contracts.py` 必须覆盖 valid model、extra field、完整 risk floors、waiting、
  retry time、lease window、naive clock、自审拒绝和 JSON Schema；
- `tests/project_workspace/test_registry.py` 验证 v0.2 layout 与 legacy manifest 拒绝；
- `tests/contracts/test_json_schema_contracts.py` 验证所有 Schema draft 合法和 project layout drift；
- 修改这些跨层字段必须同步 CONTEXT、ADR、README、docs、AGENTS 和 core specs，并运行全量
  pytest、Ruff、strict mypy、offline build 与 diff check。

## 19. T019–T022 Organization Scheduling, Spec Governance, and Runtime Binding

### 19.1 Scope and files

- `scheduling/portfolio.py` 与 `scheduling/model_router.py`：无 I/O、可重放的 Assignment/Lease 与
  run-scoped model 决策；
- `project_profile.py`：只读发现语言、build system、VCS 和 project-native rule sources；
- `spec_compiler.py`：结构化三层规则、冲突、人工 resolution 与不可变文件记录；
- `runtime_workspace.py`：organization workspace、project binding、workforce record 和
  `AgentRunAllocation` composition；
- `runtime.py`：允许注入 resolved AgentDefinition 与 bound project root，同时保持旧
  RuntimeConfig 兼容入口；
- wire contracts：`project-profile.schema.json`、`spec-conflict.schema.json`、
  `spec-resolution.schema.json`、`runtime-workspace-binding.schema.json`。

本阶段不实现分布式队列、CLI 自动 workspace binding、模型 tool loop 或证据采集。T019 的
Scheduler 是 pure decision seam；调用方负责将决策写入后续 durable WorkQueue/Lease ports。

### 19.2 Signatures

```python
active_capacity_by_agent(agents, leases, work_items=(), *, at) -> dict[AgentId, int]
PortfolioScheduler.match(work_item, role, agents, active_leases, assignments=(), *,
                         now, attempt=1, work_items=()) -> AssignmentDecision
PortfolioScheduler.schedule(work_items, role, agents, active_leases, assignments=(), *,
                            now, attempt=1) -> tuple[AssignmentDecision, ...]
ModelRouter.route(demand, agent, policy, *, now) -> ModelRoutingDecision
ModelRouter.select(demand, agent, policy, *, now) -> ModelSelection

ProjectProfile.discover(project_root, *, project_id=None, observed_at=None,
                        revision=None) -> ProjectProfile
discover_project_profile(project_root, *, project_id=None, observed_at=None,
                         revision=None) -> ProjectProfile

SpecCompiler.compile(profile, task, rules, *, compiled_at,
                     resolutions=()) -> SpecCompilation
SpecResolution.create(conflict, *, action, actor, rationale, evidence,
                      resolved_at, selected_rule_id=None) -> SpecResolution
FileSpecRecordStore.put_conflict(conflict) -> SpecConflict
FileSpecRecordStore.put_resolution(resolution) -> SpecResolution

OrganizationWorkspace.initialize(root, *, organization_id,
                                 created_at) -> OrganizationWorkspace
OrganizationWorkspace.open(root, *, organization_id=None) -> OrganizationWorkspace
RuntimeWorkspaceBinder.bind(organization, project, profile, *,
                            bound_at) -> RuntimeWorkspaceBinding
RuntimeWorkspaceBinding.compose_runtime_config(config, compiled_spec) -> RuntimeConfig
RuntimeWorkspaceBinding.validate_task_repository(repository) -> Path
FileOrganizationWorkforceStore.put_agent(profile) -> AgentProfile
FileOrganizationWorkforceStore.put_policy(policy) -> ModelPolicy
RuntimeWorkforceResolver.resolve(*, work_item, assignment, lease, selection,
                                 context_manifest_id, compiled_spec,
                                 allocated_at) -> RuntimeAgentRun
RuntimeSession(config, *, agent_adapter=None, agent_definitions=None,
               project_root=None)
```

### 19.3 Contracts and invariants

#### Scheduling and model routing

- `match/schedule/route` 不读取全局 clock、不写 store、不迁移 TaskStatus；所有时间由调用方显式传入；
- WorkItem 必须 READY，或 RETRY_SCHEDULED 且 `available_at <= now`；waiting/closed/future work 返回
  typed rejection，不创建 Assignment/Lease；
- active capacity 只统计未过期、未释放、且不属于 waiting WorkItem 的 Lease；未知 Agent Lease
  仍计入 snapshot，不能借 malformed input 隐藏占用；
- batch scheduling 按 ready、priority、risk、age、TaskId 稳定排序，新产生 Lease 立即计入后续
  capacity；Assignment/Lease ID 由业务 identity 稳定生成；
- 同一 Task 历史的 Coder/QA/Reviewer 不能由同一 Agent 承担；rejection 保留每个 candidate 的
  machine-readable 原因；
- ModelRouter 先应用 policy default/risk floor，再根据 planned files、affected layers、context
  tokens、历史 failure/QA/Review rejection 和 critical path 客观升级一档；
- route context capacity 由 composition 明确声明。非空 Context 遇到未声明容量时 fail closed，
  不能假定无限窗口；选择最小满足 tier/capacity 的稳定 route，并记录 reasons。

#### ProjectProfile and SpecCompiler

- ProjectProfile 遍历目标根目录时不执行项目命令、不跟随逃逸 symlink、不读取 `.git` 内容作为
  source text；语言/build/VCS 未知必须记录 UNKNOWN/empty facts，不猜测；
- native rule source 必须是 root-relative POSIX path、`project://<project_id>/<path>` URI、
  UTF-8 content SHA 和 source revision；profile digest 排除 `observed_at`，相同项目事实可重放；
- ProjectProfile 只发现 rule source，不把 Markdown 自然语言自动转换为 SpecRule，也不推断
  test entrypoint；
- SpecCompiler 至少需要一个 `PLATFORM_HARD` rule，并自动加入 Task 的显式 constraints；rule source
  必须属于 exact ProjectProfile/Task；
- 同 scope/key 的不兼容结构化值产生 immutable SpecConflict；层级或 priority 只用于稳定排序，
  不用于静默解决冲突；
- 未解决 conflict 返回 `SpecCompilation.status=CONFLICT` 和 `WaitingHumanRoute`；不得产生
  runnable CompiledSpec；
- SpecResolution 必须带 actor、rationale、evidence 和 exact conflict identity；hard safety conflict
  只能保留 hard rule 或终止，不能选择较弱规则；
- conflict/resolution store 使用 canonical JSON + SHA、atomic rename、immutable put；相同 identity
  等价重放幂等，不同正文复用 identity 拒绝。

#### Runtime workspace and allocation

- Organization workspace 固定包含 `organization.json`、`agents/`、`model-policies/`、`work-items/`、
  `leases/`、`metrics/`；初始化 staging + fsync + atomic rename，existing manifest 重开须完整校验；
- organization root、project root、project sidecar 两两不得重叠。Project sidecar 继续使用 T017 v0.2
  layout，Runtime 固定映射 `state/state.sqlite3`、`artifacts/`、`contexts/`、`evaluations/` 和
  `handoffs/`；
- binding 在 sidecar 的 `profile/project-profile.json` 与 `policy/runtime-workspace-binding.json`
  保存不可变记录；重开时校验 organization/project manifest、profile digest、binding digest 和
  当前 project facts，任一漂移 fail closed；
- `compose_runtime_config` 只接受同 project 的完整 CompiledSpec，将其作为唯一
  `compiled.spec` ContextSource 注入；重复 source ID 拒绝；
- workforce store 只在 organization workspace 保存 AgentProfile/ModelPolicy，envelope 和 payload
  SHA 都必须匹配；Project 不能复制 Agent 身份；
- resolver 必须同时验证 WorkItem、RoleAssignment、active Lease、AgentProfile、ModelPolicy、
  ModelSelection、CompiledSpec、persisted Context 和 role/attempt/task/project identity；Context 必须
  含 exact CompiledSpec URI/content SHA；
- 成功解析返回 `RuntimeAgentRun(allocation, agent_definition, code_root)`；tool policy ref 从 resolved
  permissions canonical hash 派生，run ID 从 assignment/context/model/prompt/spec/policy identity
  稳定派生；
- bound RuntimeSession 运行前要求 `Task.repository == project_root`。注入 definitions 必须覆盖四个
 角色且 role/key/Agent ID 唯一；多模型 case identity 使用稳定 model-set digest，不能假称单模型。

### 19.4 Validation and error matrix

| 输入/状态 | 检测点 | 结果 |
|---|---|---|
| naive scheduler/router/allocation time | public boundary | `SchedulerInputError`/`ValueError`/`RuntimeAllocationError` |
| waiting/closed/future WorkItem | `PortfolioScheduler.match` | REJECTED + stable code，无 Assignment/Lease |
| Agent inactive/role mismatch/capability missing/capacity exhausted | Scheduler | 对应 typed rejection，继续考虑其他 Agent |
| 同 Task 跨 delivery role 复用 Agent | independence guard | `SELF_REVIEW` rejection |
| batch 重复 Task ID | `schedule` | `SchedulerInputError` |
| ModelPolicy/Agent mismatch 或没有 tier/capacity route | ModelRouter | REJECTED + `ModelRoutingRefusal`；`select` 抛 `ModelRoutingRejected` |
| root 缺失、symlink escape、非 UTF-8 rule、revision mismatch | ProjectProfile | typed ProjectProfile error，不返回 partial profile |
| 缺 PLATFORM_HARD、rule source 与 profile/task 不符 | SpecCompiler | `HardPolicyMissing`/`SpecSourceMismatch` |
| 未解决结构化冲突 | SpecCompiler | CONFLICT + WAITING_HUMAN route，无 CompiledSpec |
| resolution 缺 evidence、引用未知 conflict、放宽 hard safety | resolution/compile | `SpecResolutionRejected` |
| immutable spec record 被改写或磁盘 digest 不符 | FileSpecRecordStore | conflict/corruption typed error |
| organization/project/sidecar overlap 或 manifest/layout 漂移 | workspace open/bind | RuntimeWorkspace conflict/corruption |
| current project facts 与 persisted profile 不同 | binding validate | `RuntimeWorkspaceConflict` |
| Task.repository 与 binding project root 不同 | Runtime binding/session | `RuntimeWorkspaceConflict`/`RuntimeConfigurationError` |
| Lease 过期、selection policy/model 不匹配、Context 缺 compiled spec | resolver | `RuntimeAllocationError`，Agent 不启动 |

### 19.5 Good / Base / Bad

- **Good**：两个 READY WorkItem 以同一显式 clock 调度；第一个新 Lease 被第二个 capacity check
  观察；每个 run 使用独立 Assignment、Context、CompiledSpec、tool policy 和 model selection；
- **Base**：本地临时 Git 目录 + Markdown/manifest fixtures + fake adapter 即可验证全部组合，不需要
  provider 网络、容器、消息队列或数据库服务；
- **Bad**：Scheduler 内直接写 TaskStatus；把未知 context window 当无限；按“平台规则优先”静默
  吞掉项目冲突；在目标项目写 `.ase`；让 Runtime 用过期 Lease 或不含 exact CompiledSpec 的 Context。

### 19.6 Tests required

- `tests/scheduling/`：readiness、priority/risk/age、capacity aggregate、expiry/release/waiting、batch
  新 Lease、no-self-review、deterministic IDs、risk/complexity/failure/context routing 和 refusals；
- `tests/project_profile/`：Python/Java/C++/Go/TypeScript markers、multiple build systems、Git revision、
  native rules、stable digest、unknown facts、symlink/UTF-8/revision fail-closed；
- `tests/spec_compiler/`：clean compile、Task constraints、conflict route、hard safety、resolution evidence、
  record immutability/corruption、CompiledSpec ContextSource；
- `tests/runtime_workspace/`：atomic organization layout、overlap/corruption、binding reopen/profile drift、
  fixed paths、workforce envelopes、allocation cross-object guards、exact CompiledSpec Context 和 bound
  RuntimeSession repository；
- `tests/contracts/`：四个新 Schema 与 Python model 正反例；
- 全量 pytest、Ruff check/format、strict Mypy、offline build 和 `git diff --check`。

### 19.7 Wrong vs Correct

#### Wrong

```python
# Hidden mutation, guessed policy precedence, and project pollution.
task.status = "QA"
agent = first_agent_with_capacity()
model = "largest-model"
write_json(project_root / ".ase" / "profile.json", guessed_profile)
compiled = {**organization_rules, **project_rules}
```

#### Correct

```python
decision = scheduler.match(work_item, role, agents, active_leases, assignments, now=clock.now())
model_decision = router.route(demand, agent, policy, now=clock.now())
profile = ProjectProfile.discover(project_root, project_id=project.project_id)
compilation = SpecCompiler().compile(profile, task, rules, compiled_at=clock.now())
if compilation.waiting_route is not None:
    persist_waiting_human(compilation.waiting_route)
else:
    binding = binder.bind(organization, project, profile, bound_at=clock.now())
    runtime_run = resolver.resolve(
        work_item=work_item,
        assignment=decision.assignment,
        lease=decision.lease,
        selection=model_decision.selection,
        context_manifest_id=context.context_id,
        compiled_spec=compilation.compiled_spec,
        allocated_at=clock.now(),
    )
```

后者把调度、规范、workspace 和运行身份都保持为可验证事实；任何边界失败都在 Agent 启动前
fail closed，且没有把组织元数据写进目标代码目录。

## 20. Evidence capture and typed tool protocol (T023–T024)

### 20.1 Scope and signatures

- `RunEvidenceSession.capture_command(operation_id, executor, arguments, timeout_seconds=...)`
  captures the requested tokenized argv, bounded stdout/stderr/cwd, return code, duration and
  typed timeout/rejection/start-failure outcome. The command is executed only through the existing
  `CommandExecutor` port.
- `RunEvidenceSession.record_diff(...)`, `record_test(...)` and `record_agent_result(...)` create
  discriminated `EvidenceRecord` values. Test records may reference only a command record from the
  same `RunEvidenceIdentity`; Agent usage records carry provider-neutral `AgentUsage` counts.
- `RunEvidenceSession.seal(outcome)` writes one `RunEvidenceManifest` containing the ordered evidence
  IDs. `FileEvidenceStore.put/get/seal_run/get_run` use canonical JSON, SHA-256 and atomic rename;
  an existing ID is immutable and equivalent replay is idempotent.
- `PolicyBoundToolRegistry.execute(request)` accepts only `ReadFileRequest`, `WriteFileRequest`, or
  `RunCommandRequest` carrying `run_id`, `role` and `operation_id`. It returns a typed success or
  `ToolRejectedResult`; no free-text shell or verdict/artifact/state mutation operation exists.

### 20.2 Invariants and error matrix

| Input or failure | Detection | Required result |
|---|---|---|
| Secret in argv, output, cwd, diff or Agent error | shared `redact_text` before persistence/hash | replacement token plus redaction counts; original secret is never durable |
| Command timeout, policy rejection, failed start | `RunEvidenceSession.capture_command` | persist failed evidence first, then re-raise the typed execution error; same operation replays the record |
| Changed content under an existing evidence ID | `FileEvidenceStore.put` | `EvidenceConflict`; never overwrite |
| Tampered JSON, digest, filename or manifest references | store read/seal validation | `EvidenceCorruption`/`RunEvidenceConflict`; no partial result |
| Test references another run's command | `record_test` | `EvidenceCaptureError` |
| Tool request role/run differs from bound registry | `PolicyBoundToolRegistry.execute` | `ToolRequestIdentityMismatch`; do not execute |
| Path traversal, `.trellis`, artifact/state/verdict/report path | `WorkspacePolicy` plus role guard | typed `PATH_DENIED` rejection |
| QA write outside `tests/**`; Reviewer write anywhere | role guard | typed `PATH_DENIED` rejection |
| shell interpreter or unallowlisted argv | `WorkspacePolicy.authorize_command` | typed `COMMAND_DENIED` rejection; no shell invocation |
| non-UTF-8 read or oversized file/output | bounded read/decode | typed rejection or truncated result with explicit marker |

### 20.3 Good / Base / Bad

- **Good**: redact first, hash the canonical sealed envelope, persist immutable evidence, and route
  every tool result through the bound role/run policy. A rejected command is evidence, not a PASS.
- **Base**: local filesystem stores, fake `CommandExecutor`, and fake Agent adapter are sufficient
  to test replay, tamper detection, role isolation, and schema compatibility offline.
- **Bad**: persist provider raw response, hash before redaction, accept a free-form `shell` field,
  let QA edit production code, let Reviewer write a report file, or use tool success as a verdict.

### 20.4 Tests required

- `tests/evidence/`: command success/failure/timeout/replay, redaction, bounded diff, same-run test
  linkage, Agent usage, manifest sealing, immutable store and corruption paths;
- `tests/tools/`: typed request adapter, no shell/verdict fields, Coder read/write/command, QA and
  Reviewer write refusal, denied paths, and identity mismatch;
- `tests/contracts/`: every evidence, manifest, tool request and tool result wire payload must pass
  its Draft 2020-12 schema; malformed discriminators and unknown fields must fail;
- full pytest, Ruff check/format, strict Mypy, offline package build and `git diff --check` before
  integration.

### 20.5 Wrong vs Correct

```python
# Wrong: unbounded provider output and an ambient shell escape hatch.
result = subprocess.run(agent_text, shell=True, cwd=project_root)
write_json(sidecar / "evidence.json", result.__dict__)
```

```python
# Correct: typed request, bound policy, redacted immutable evidence.
request = RunCommandRequest(
    run_id=run_id, role=role, operation_id="qa.tests", argv=("pytest", "-q")
)
tool_result = registry.execute(request)
command_evidence = evidence_session.capture_command("qa.tests", executor, request.argv)
manifest = evidence_session.seal(RunOutcome.SUCCEEDED)
```

The tool protocol is an application seam in v0.1. Runtime exposes the evidence store and sidecar
roots, but every future role adapter must explicitly wrap tool calls with `RunEvidenceSession`; no
Agent receives direct filesystem, subprocess, verdict, or state-store access.
