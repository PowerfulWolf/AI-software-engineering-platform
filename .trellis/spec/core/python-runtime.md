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
