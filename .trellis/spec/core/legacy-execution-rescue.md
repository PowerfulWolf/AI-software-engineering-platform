# Legacy execution rescue

## Scope / trigger
Only a nonterminal local native Coder invocation with a real exact invocation-start and historical
claim but genuinely missing final outcome and original capture/stop ledger. This is a new
engineering disposition, never reconstruction of the old execution.

An immutable `capture-start-<run_id>.json` may exist without a stop record when the old runner
crashed or was interrupted before finalization. A start-only record is retained input, not proof
that the process stopped and not a checkpoint or outcome. Legacy rescue may continue only after
the record is re-read and its request, claim, scope, task intent, checkpoint revision, policy
digest, and manager-owned worktree path match the current facts. A `capture-stop` or receipt for
the same Run still selects the native original-record handling path; a malformed or mismatched
start record fails closed. Rescue never writes, replaces, or completes any original record.

## Signatures and wire

- `manager/legacy_containment.py`: `TrustedLocalBootObserver.observe() -> LocalBootObservation`
  (`machine_sha256`, `boot_session_sha256`, `booted_at`), twice observed stable. The exact
  `LegacyExecutionContainment` embeds `original_start`, `original_claim`, native child
  `requirement_id`, `dispatch_sha256`, `scope`, `task_intent_sha256`, `boot`, `containment_sha256`.
- `manager/legacy_local_execution.py`: `TrustedLegacyLocalExecutionObserver.observe(*,
  worktree_root: Path, boot: LocalBootObservation) -> LegacyLocalExecutionSurvey`, with exact
  worktree/device/account/boot/scanner boundary, observed time, bounded blocker enums and SHA.
  `LegacyRescuePrerequisiteError(code, safe_message, next_action)` is a typed expected wait.
  No original PID/argv/environment or historical stopped boolean is invented.
- `manager/baseline_production.py`: `BaselineProposeCommand.purpose` and
  `BaselineExecuteCommand.confirm_legacy_containment: Literal[True] | None`.
  `BaselineOperatorAuthorization.for_plan(..., confirm_legacy_containment=True)` binds the
  human declarations to the exact plan/facts/principal digest, not to request text alone.
- `method=operator_confirmed_local_stop` requires **only** the separate
  `confirm_local_execution_stopped: Literal[True]`; `method=os_reboot` requires **only** the
  existing `confirm_legacy_containment`. Both absent for source rebind; both present is invalid.
- `manager/execution_baseline.py`: `ExecutionBaselineService.propose(target_base_ref,
  input_mode=preserve_draft, purpose=legacy_workspace_rescue)` captures full facts;
  `execute(plan_sha256, authority=BaselineOperatorAuthorization)` publishes once.
- `work_queue/baseline.py`: `consume_baseline(..., cursor, validate_new_consumption)` calls the
  trusted callback only after checking no existing consumption. The callback revalidates complete
  current capture, inventory and same-device stable boot before the SQL transaction proceeds.

Console `POST /api/v1/operations` wraps the normal exact Project/Requirement checkpoint plus
`PROPOSE_EXECUTION_BASELINE` with `purpose=legacy_workspace_rescue`, `input_mode=preserve_draft`,
original `task_id`, `expected_task_revision`, `expected_task_intent_sha256`,
`expected_work_item_id`, `expected_source_revision` and unchanged `target_base_ref`.
Execution selects only `EXECUTE_EXECUTION_BASELINE`, exact `expected_plan_sha256`, human
`reference` and the method's exact human confirmation. HTTP cannot assert boot/survey facts or
original stop. Console contract 3 supports local-stop confirmation; contract 2 retains old reboot
plans. `legacy_rescue_preparation` is typed READY with exact plan or WAITING without any plan,
approval or binding. Expected incomplete/active observations return a successful check, not a
failed delivery or Pydantic error. All ValidationError inputs are replaced with fixed safe Chinese.

## Persistence and replay

New facts reuse `state/execution-baselines/<task_id>` append-only `baseline-plans`,
`baseline-authorities`, `baseline-starts`, `baseline-bindings`; queue `work_queue_execution_baselines`
stores the exact plan/binding/next item consumption. No table migration or old-record rewrite.
Bindings carry `purpose` and `legacy_containment_sha256`; readers load the complete plan and
operator authorization rather than treating the hash alone as isolation authority.

Binding publication before SQL commit is replayable: an already authorized original boot proof
remains valid after a later stable boot on the same device, provided the complete workspace is
unchanged. Preparing again for the same start returns the original sealed plan after verifying
the exact unchanged snapshot; retry the original exact approval without a second binding. Completed
queue consumption replays without reobserving a later boot or duplicating budgets. A new prepared
but not approved plan can always be prepared again after source/boot facts drift.

## Contracts
`purpose=legacy_workspace_rescue` reuses baseline capture/plan/binding/queue contracts but selects
the unchanged prior execution base, preserve_draft mode and exact original source. It must not
mutate source files, HEAD, index or branch. All current dirty bodies are captured against immutable
Git, checked against frozen write/deny policy, and verified twice under Task lock and queue fence.

An OS observer reads current stable local machine identity, boot-session identity and boot time.
For `method=os_reboot` (the omitted legacy default), the observed boot must postdate the exact
invocation start. This proves containment only together
with a separate trusted engineering authorization explicitly attesting that the original native
execution used this same local computer, was never migrated/remote, that a whole-computer reboot
actually happened after the original execution, and that the time evidence is trusted. The original
Run lacks host identity; therefore automatic EngineeringAdmission is refused.
Attestation is human-supplied engineering evidence, not an owned runner stop or autonomous recovery.

Service restart, an expired lease, a free lock, absent PID or a process scan cannot establish this
condition. A second current OS observation must match before queue publication; caller-supplied
OS booleans/dates/PIDs cannot bypass the observer. Original historical UNKNOWN/outcome gaps remain.

### Current local survey and explicit supplied cessation evidence

When boot does not postdate the original start, collect a fresh trusted survey over the current
effective-account local execution boundary and the manager-owned original checkout. Fixed bounded
OS queries inspect native Codex execution/wrappers and attributable cwd/open workspace references. App-server
identity alone is not native delivery execution. Unknown ownership/state, query denial/truncation,
target-associated processes and incomplete coverage refuse preparation. Commands never signal
discovered processes, read environment variables or publish raw arguments. The original exact
request/claim must still prove native local routing; unknown fallback or remote boundaries refuse.

### Safe diagnosis of an incomplete current survey

An incomplete survey continues to return `PROCESS_SCAN_INCOMPLETE` and refuses recovery.
The observer emits one WARNING on its module logger with fixed `phase`, exception-class
`reason`, and numeric `elapsed_seconds`. The phase identifies the inventory, path or final
identity check which could not complete. Do not log the exception message/traceback, discovered
PID, argv, environment, cwd, open-file body or retained root. The warning is operational
diagnosis only: it is not a persisted execution fact, receipt, historical cessation proof,
or permission to increase a deadline, skip coverage or retry a model invocation.

Fixture tests inject OS/query failures at the actual observer seam and verify the original
fail-closed blockers, bounded safe fields and no warning for a complete idle survey. No schema,
survey digest, scanner identity, timeout or admission rule changes for this diagnostic.

This survey is **not** a historical process-stop proof. A trusted human with ENGINEERING duty
supplies the missing facts by confirming the original invocation always ran on the same local
computer/account, was never moved or remote, and the original invocation **and all its derived
tools** have actually ended and cannot modify the workspace again. They accept UNKNOWN and
authorize preserved-draft execution from remaining work allowance. Without that exact declaration
no machine EngineeringAdmission may continue. Persist it in immutable authority and
HumanActionEvent(SUPPLY_EVIDENCE) with the authority URI; preserve old reboot event bytes/notes.

The local-stop Console flow displays the complete declaration next to the approval button;
clicking “批准保留进度并继续原需求” supplies the exact confirmation and approval together,
without a separate checkbox. Loading, polling or preparing a plan never supplies that declaration
or executes recovery. The click callback still validates the current plan, Project/Requirement,
checkpoint, capabilities, control readiness and connected button before posting
`confirm_local_execution_stopped=true`. The separate legacy reboot checkbox retains its existing
behavior. A disconnected, stale or unreadable approval cannot become valid merely by re-rendering.

Before preparation completion, execution and new queue consumption, freshly recheck the survey,
stable boot, all claims under Task lock/SQL fence and complete snapshots. Survey times and unrelated
process changes do not invalidate a valid plan: independently verify the typed boundary and retain
the sealed observation body/hash for exact facts comparison. Pin the approved observation before
collect. A genuinely later same-device boot may be accepted on replay with fresh same-account/path
survey; do not alter sealed proof. Already-consumed publication remains idempotent without rescanning
obsolete inputs. Survey/capture worktree paths must match in the plan model itself.

Unknown work is not refunded or classified as provider failure. Exact queue consumption keeps the
old WorkItem/history and reserves a distinct next work attempt/WorkItem. New Run and Context require
a real claim and the original permissions; independent QA/Review and same-candidate gates remain.

### Reclaimed claim before the legacy invocation

The real claim immediately before the contained invocation may have expired without an invocation
start. Under the Task lock and queue SQL fence, inspect its immutable claim, exact dispatch
generation, lease end, `LEASE_EXPIRED` event and the later `CLAIMED` event in order. Require no Run,
Context, knowledge preparation, model route, preflight checkpoint, capacity receipt or matching
preflight receipt in that claim's observed lifetime. A preflight receipt is written before its
checkpoint; a crash between those writes is activity, even when the checkpoint is absent. Its
integrity, Task, Team, Project, Repository, Requirement, source and checked time must be inspected;
matching activity refuses the uninvoked proof. An unreadable ledger also refuses. Do not infer
no-start solely from a missing checkpoint or expired lease.

Seal the independent `ReclaimedUninvokedClaimObservation` inside `BaselineInvocationProof` and
`BaselineQuiescenceProof`; retain the old Run and all prior claim facts. The corresponding
standalone generated JSON Schemas are `reclaimed-uninvoked-claim-observation.schema.json`,
`baseline-invocation-proof.schema.json` and `baseline-quiescence-proof.schema.json`. Rescanning
with a published legacy binding must reproduce the same proof without a new claim or budget change.

## Validation matrix
| Case | Behavior |
| --- | --- |
| OS boot before/equal original start | Current local survey + new exact engineering cessation declaration |
| Unreadable OS identity or incomplete survey / live execution | WAITING explanation, no plan or new invocation |
| Original final result now exists | Reject rescue; use original result replay |
| Start-only capture binds exact current facts | Validate it read-only, then allow new containment facts; preserve its bytes |
| Start-only capture is malformed, mismatched, or worktree-drifted | Reject rescue and preserve the original UNKNOWN history |
| Missing original claim/start or nonlocal execution | Reject; no new invocation |
| Exact earlier expired claim, no preparation or execution facts | Seal reclaimed uninvoked proof and preserve old Run |
| Receipt written before preflight checkpoint, or unreadable preflight ledger | Reject uninvoked proof; keep queue and history unchanged |
| Rescue authorization without exact same-device attestation | Reject before queue/source effects |
| Platform policy admission or changed source/input mode | Reject; explicit engineering decision required |
| Dirty/protected/ignored/staged drift or incomplete body | Preserve full现场; no reset/clear |
| Policy-authorized ignored regular source file | Include it in the immutable mutation capture; execution caches remain outside the capture |
| Valid complete snapshot + OS observation + exact decision | Append binding, reserve next work, same Task |
| Crash/repeated approval | Exact record replay, no duplicate budget or WorkItem |

## Required tests
OS observer success/refusal, exact request/claim/boot binding, immutable legacy digests, no automatic
authority, complete retained draft and no filesystem mutation, unknown no-refund accounting,
public operation schema/Host/native completion, UI capability/stale guards and Chinese next steps.

Focused commands:
`pytest tests/manager/test_legacy_containment.py tests/manager/test_legacy_snapshot.py`,
`pytest tests/manager/test_legacy_rescue_delivery.py tests/web_console/test_legacy_rescue_acceptance.py`,
`node --test tests/team_view/browser/legacy-rescue.test.cjs` (configured Playwright NODE_PATH).
The public fixture must reach original Task DONE through distinct native Coder/QA/Review claims,
same candidate SHA, preserve unknown start/no original outcome, keep files/index/HEAD/branch,
record `HumanActionEvent(SUPPLY_EVIDENCE)` and validate all four updated static Schema documents.
After delivery, traverse `_invocations` across the complete Task queue: the old unknown has exact
legacy containment but no outcome/receipt, and the succeeding Coder/QA/Review have real outcomes.
Verify inherited baseline digests through immutable parent/consumption lineage while preserving
QA/Review candidate sources; foreign, missing, cyclic or stale-epoch lineages remain rejected.

## Good / base / bad
- Good: old local UNKNOWN plus genuine same-device post-invocation reboot, explicit engineering
  confirmation and complete legal snapshot; next ordinary work attempt delivers same Task.
- Base: only ASE restarted; survey can prepare preserved draft but never becomes automatic stop proof.
- Bad: inferred stop from lease/PID, invented provider refund, protected ignored input, automatic
  policy approval or new duplicate Task; refuse and preserve all files and historical records.

## Wrong vs correct
Wrong: manufacture a timeout stop from a restart, accept a user `stopped=true`, or reset the Task.
Correct: capture new engineering facts honestly, require exact human attestation where old machine
identity is absent, preserve the old unknown Run and use a separately claimed successor attempt.
## 本机调查的控制会话归属（2026-10-08）

### 1. Scope / Trigger

修复调查者也使用 Codex 时的全账户假阻塞。此调查仍是旧 UNKNOWN 的当前辅助事实，不产生
历史停止证明或自动审批。普通维护 checkout 与被救援的 manager-owned Coder checkout 分开。

### 2. Signatures

`_Process(pid, ppid, state, birth, command, executable_name)` 只存在调查内存；
固定 ps 查询为 `/bin/ps -ww -U <uid> -o pid=,ppid=,uid=,stat=,lstart=,command=`。
`_executable_name(pid)` 使用 macOS `proc_pidinfo(PROC_PIDTBSDINFO)` 的 kernel name，
Linux 使用 `/proc/<pid>/exe`；不是 argv 内目录名字。macOS 已更新/删除的旧 app 二进制
仍可能正在运行，不能因 PIDPATH 的 ENOENT 将它看成已退出或令本账户调查永远不完整。
`_idle_terminal(process)` 只接受 S/I 状态、明确 shell basename 与固定交互/login flags，无执行命令。

### 3. Contracts

- 根可执行身份与动作分开识别：真实 `codex exec` 和 `e` 阻塞；实际 CLI 的未知参数、
  未核实的 sandbox、apply/default prompt 和包装路线保守阻塞。仅下节核实的桌面 CUA
  工具沙箱可免账户级 wrapper 推断；不能用四个子命令白名单放行未知 CLI。
  `_codex_action` 按实际动作位置跳过明确全局选项和值，`_argv_blocker` 按 shell command、
  script/module/env 的启动位置识别 wrapper；参数中的 app-server/exec/e 和会话名称不是动作。
- 独立 `codex resume`、code-mode-host 和明确控制 daemon 不属于旧平台 `codex exec`。
  桌面 Resources 下的 resume 与未知 wrapper 不获得全账户维护豁免。
- 仅明确空闲 shell 的 cwd 可以不算访问；Python/Node、运行 shell command、孤儿工具及其他
  未知进程的原工作区 cwd 仍阻塞。控制会话若 cwd 就在原 Coder checkout 也阻塞。
- 真实打开的工作区文件/目录始终检查，控制进程的任意祖先/后代不获文件豁免；仅调查进程
  自身不参与访问判定。原生执行后代的 cwd 保持执行归属。
- 第二清单的 command/executable/PPID 或 cwd 归属改变时，重查已 covered PID 的路径。
  Unix exec 不改变 PID/birth，不能只靠出生时间一致沿用旧空闲分类。重查前撤销旧 coverage，
  活进程重查无 cwd/路径 coverage 时返回 PROCESS_SCAN_INCOMPLETE。
- 未知状态、身份权限异常、截断、扫描时限、缺失 coverage 和 PID 复用仍 WAITING。
  不信任 caller 传入 PID/进程豁免名单；不发信号、不读环境、不发布 raw argv/kernel names。
- wire `local-execution-v1`、封存摘要及同账户/设备/路径/boot 比较保持；这是 v1 误分类修正，
  无新增持久化结构、能力或审批方法。旧 sealed records 不重写。

### 4. Validation & Error Matrix

| 情况 | 结果 |
| --- | --- |
| 维护 resume/控制服务在另一 checkout，原 checkout 空闲 | 可以准备；仍需 exact 工程确认 |
| 明确空闲 shell cwd 在原 checkout | 不仅凭 cwd 阻塞 |
| 普通工具或孤儿 Python/Node cwd 在原 checkout | WORKTREE_PROCESS_ACTIVE |
| 真实 exec/e、未知 native CLI 或 wrapper | CODEX_EXECUTION_ACTIVE / CODEX_WRAPPER_ACTIVE |
| 维护会话打开原 checkout 文件或交互 cwd 就在原 checkout | WORKTREE_PROCESS_ACTIVE |
| shell 在两次清单之间 exec 成 resume/command | 重查路径，不能沿用已覆盖的空闲事实 |
| kernel name 不可读、身份变化或调查不全 | PROCESS_SCAN_INCOMPLETE；无 plan/authority/consumption |

### 5. Good / Base / Bad

Good：保持维护 Codex/ASE 在线，在原隔离 checkout 准备；审批仍是独立工程声明。
Base：关闭真正使用原 checkout 的工具后复查。Bad：kill 调查者、猜目录名即执行器，
或将整个维护进程树从文件检查中剔除。

### 6. Tests Required

`tests/manager/test_legacy_local_execution.py` 覆盖内核名称、exec/e/未知 CLI、维护入口、
idle shell、孤儿工具、真文件、same-PID exec drift、Linux/macOS 和截断/身份拒绝。
`tests/manager/test_legacy_rescue_delivery.py` 的本机停止两场景使用真实 observer，仅替换
固定 OS reads；公开 Host 必须保持同 Task、草稿、旧 UNKNOWN、预算和独立 QA/Review。
Console/containment/Schema 增量回归保证 WAITING 无 plan/approval、新浏览器字段不能伪造调查。

### 7. Wrong vs Correct

Wrong：`if "codex" in command: block()` 或 `if control_ancestor: ignore_all_files()`。
Correct：读取内核可执行身份，分类明确控制入口，按原 checkout 的实际 cwd/文件事实核验，
仅豁免明确空闲终端；再由已有 exact 工程授权供给缺失的历史停止事实。

## 桌面 CUA 沙箱的正向来源分类（2026-10-09）

### 1. Scope / Trigger

控制入口自身不是执行，但它启动的固定桌面工具可能仍被全账户 `sandbox` 分类挡住。
必须核实当前真实来源；不要求使用者关闭维护会话，也不把所有 sandbox 改成仅看 cwd。
当前经过 OS 验证的路线仅为 macOS ChatGPT.app 的 CUA REPL。

### 2. Signatures

`manager/legacy_local_execution.py` 内部：

```python
_executable_path(pid: int) -> str | None
_desktop_sandbox_chains(processes: dict[int, _Process], root: Path
                       ) -> dict[int, tuple[_DesktopProcessIdentity, ...]]
_verified_desktop_sandbox_pids(before_chains, after_chains,
                             before_covered: frozenset[int], covered: set[int]
                             ) -> frozenset[int]
```

`_DesktopProcessIdentity` 仅存内存中的 PID/PPID/birth/command/kernel name/native path。
macOS 固定 `proc_pidpath` 查询仅用于正向分类；查询失败、更新删除导致 ENOENT 或未知路径
表示没有取得正向身份，不能推断退出。Linux 不获得这条桌面路线的豁免。
`observe(worktree_root, boot)`、wire/摘要、`local-execution-v1` 和审批 API 不变。

### 3. Contracts

- 固定五级链：真实 `codex sandbox → node_repl → node(cua-repl.mjs) → codex app-server → ChatGPT`。
  每一级来自当前账户的两次清单，PID、PPID、birth、command、kernel name 和 native path
  均一致，全部有 fresh cwd/file coverage。允许 R/S/I 之间的瞬态变化，不允许 stopped、
  zombie、未知状态、链不全、环、reparent 或身份/程序漂移。
- 受信 bundle 固定为已核实安装位置 `/Applications/ChatGPT.app`，不是由进程 native path
  自行推导或 caller 指定。其他安装位置/平台暂不授予来源分类，保持 wrapper 拒绝。
  所有路径属于该 bundle：`Contents/MacOS/ChatGPT`、
  `Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`、
  `Contents/Resources/cua_node/bin/node_repl` 和 `node`；sandbox 与 app-server 的真实 binary
  相同。node 主入口精确使用同 bundle 的
  `Contents/Resources/cua_node/lib/node_modules/@oai/cua-repl/bin/cua-repl.mjs`，
  无未知额外参数。按实际位置解析 app-server 与 sandbox 动作；sandbox `--` 后执行器
  必须是同 bundle node。临时 `kernel.js`/`trusted-worker.js` basename 不是信任根。
- 只在完整扫描后取消上述 sandbox 的全账户 `CODEX_WRAPPER_ACTIVE`；observer 外没有
  `ignored_pids`。控制入口、封装、任意子工具和孤儿的真实 cwd/open-file 检查全保留。
  实际占用原 checkout 仍 `WORKTREE_PROCESS_ACTIVE`；显式载荷/工作目录参数指向原
  checkout 时不授予来源豁免，即使调查瞬间 cwd 在其他地方。
- 真实 `exec/e`、`ase task run`、普通 shell/script 封装、未知/orphan sandbox 和其他 app
  路线不获得这个分类。不得从 argv 控制词、临时文件名或 caller PID 白名单推断来源。
- 原扫描 deadline/限长、PID reuse、二次 drift 重查、完整 coverage 和拒绝行为保持。
  归属分类不造历史 stop/result，不自动批准，不改 Task/旧 Run 或工作区。
- 这是 v1 误分类修正，无新持久化事实/权限。旧 sealed survey/Operation 不重写；本次复查
  产生新当前事实，用户仍须对精确方案确认实际停止前提。

### 4. Validation & Error Matrix

| 情况 | 结果 |
| --- | --- |
| 同 bundle 固定链，稳定且完全覆盖，另一个 checkout | 无账户级 wrapper 假阻塞 |
| 同链或任意子工具的 cwd/打开文件位于原 checkout | WORKTREE_PROCESS_ACTIVE |
| sandbox 载荷/声明工作目录指向原 checkout | 无豁免，保留 wrapper 阻塞 |
| 不同 bundle、伪 executable/title、不同脚本、未知 payload、孤儿/缺链 | CODEX_WRAPPER_ACTIVE |
| 控制链中出现真实 exec/e 或独立真实 exec/e | CODEX_EXECUTION_ACTIVE |
| 祖先或 sandbox PID/birth/PPID/command/native path 漂移 | 不复用维护来源分类 |
| native 正向路径不可读但普通 coverage 完整 | 保守 wrapper 阻塞，不假称退出 |
| cwd/file 覆盖失败、identity reuse、权限/超时/截断 | PROCESS_SCAN_INCOMPLETE，无方案 |

### 5. Good / Base / Bad Cases

Good：维护会话保持在线，真实原 K1 只读调查无误报；Base：真实工具占用原工作区时等待
其正常结束；Bad：让使用者 kill 调查者，或因控制 ancestry 跳过全部源文件检查。

### 6. Tests Required

`test_legacy_local_execution.py` 先 red 复现真实五级链；覆盖 bundle/脚本/title/payload
假冒、native 路径失败、祖先-only drift、reparent、真实 exec/e、全部 cwd/file/声明参数、
Linux 无新路线及 coverage 拒绝。`test_legacy_rescue_delivery.py` 的两个 local-stop 公开
Host 场景必须在该真实形状的维护链存活时完成同 Task/UNKNOWN 保全、绑定崩溃重放和
独立 QA/Review；仅替换固定 OS reads，不 mock 正向分类。真实 K1 的只读复核记录完整
工作树与 index 的前后摘要，无生产方案、审批或队列写入。

### 7. Wrong vs Correct

Wrong：`if parent_contains_codex: ignore_tree()` 或按 `kernel.js` 文件名放行。
Correct：双清单 + native path 核实固定协议入口，只改最终 wrapper 分类，完整工作区
检查仍独立拒绝；历史停止仍由现有 exact 工程声明补足。

## 保留源码的敏感信息分类与准备失败（2026-10-09）

### Scope / Signatures

v2 完整 mutation bodies 是可复用代码输入，不能先脱敏再保存。通用文本的
`secret_assignment` 不能把 Python 的 `password=settings.password`、
`secret = foreign / "secret.json"` 当成秘密字面值。

- `redaction.source_secret_occurrences(content, *, source_path: str | None = None)` 仅返回
  `tuple[RedactionOccurrence, ...]`，不返回“已脱敏”的原始正文；默认及未知类型走原
  `redact_text`。支持经过验证的 `.py` 相对路径、AST 语法与完整 tokenize 边界。
- `redaction.patch_secret_occurrences(content)` 只从真实 `diff --git a/... b/...` 和
  无源码标签的 `@@` hunk 选择语言；分开 old/new 侧、验证行计数后检查代码。
  metadata、未知格式、标签、错数、超长计数始终用通用检测。
- `MutationTextBody(text, mode, source_path=None)` 的 source_path 只存在内存，
  `compare=False`，不新增 wire 或 digest 字段。`read_mutation_body(root, relative_path)` 与
  Git base blob 读取传入已被 WorkspacePolicy 校验的实际路径。
- `CapturedMutationBody` 校验 UTF-8 大小/NUL/hash/mode，不能单独授予源码例外；拥有
  `RelativePath` 的 `CapturedMutation` 对 before/after 调 `to_body(source_path=path)`，
  `CapturedMutations.to_capture` 再检查同一路径。所有计划落盘、读取和重放都经过父级校验。

### Contracts

- `.py` 源码例外只按 AST 可证明的声明和值分类：敏感字段可无默认值地声明，或使用
  Name/Attribute、`|` union、Subscript、Tuple、`None`/Ellipsis 组成的类型注解；函数参数
  遵守同一规则。字符串 forward annotation、调用及任意字符串类型不获得例外。注解本身
  不批准 RHS/default，后者必须独立检查，不能把 `token: str = "实际凭证"` 当成声明放行。
- 可证明的 RHS 仅包括 `None`、single-name 对象同名字段引用、single-name `/` 带路径符号
  且通过通用检测的普通固定字符串，以及 single-name 对象的精确 `field_name + "_hash"`
  固定下标，如 `token = row["token_hash"]`。任意 identifier、未知 dotted value、其他
  下标、调用接收者、动态下标和插值不获得例外。
- 构造调用例外仅限在调用之前已出现的、无 alias 的 module-level `dataclasses`/`secrets`
  导入或对应成员导入。`dataclasses.field` 不接受 positional、`default`、`default_factory`、
  `metadata` 或 `**kwargs`，仅接受布尔 `init/repr/compare/hash/kw_only`，`hash` 另允许
  `None`。`secrets.token_bytes/token_hex/token_urlsafe` 必须只有一个 1–4096 的整数
  literal positional size；布尔、变量、字符串、keyword 或额外参数均不获得例外。
- 可信导入须经完整源码的保守静态绑定检查：任意作用域的重绑、同名参数/定义、删除、重复
  或 wildcard 导入、match capture、成员变更均撤销例外；模块或函数只能在精确构造 callee
  位置使用，传给未知调用、容器或 alias 等 escape 也撤销例外。`exec/eval/globals/locals/`
  `__import__/__builtins__`、相关 alias、builtins 命名空间或动态/反射入口不能绕过检查。
  不执行 import、构造函数或源码，不推断未知调用的安全性。
- partial patch 只使用已观察到且计数有效的 old/new hunk 事实，不能从遗漏的完整文件推断
  导入或可信绑定；未观察到 `secrets` 导入的 `token = secrets.token_urlsafe(32)` 仍拒绝。
  完整 capture 的源码结论不能冒充 partial patch 的额外上下文。
- 字符串、注释、f-string（含嵌套及三引号）和 t-string 全 span 均不获得例外；强特征
  OpenAI/AWS/GitHub key、Bearer 和 PEM 独立检查整个原正文，不因 span 替换而丢失。
- AST/tokenize 的未知语法及资源限制使用保守结果，不执行源码。span 游标按位置单调移动，
  不在每次 assignment 上线性遍历所有字符串。
- v2 working/staged patch、完整 body、CapturedMutations、baseline replay 和 required execution
  Context 使用同一入口。Context 的 instructions 仍用通用 redactor；只有已绑定完整 patch
  用源码检查，任何 body/patch 均保持 byte-for-byte、SHA 和当前 index/HEAD/branch。
- v1 recovery、普通日志、URI、知识和 Evidence 的 `redact_text` 不变，其他语言和未知配置仍保守。
  不按 `src/**`、`tests/**` 或调用者提供的“安全”标记豁免。
- 工程授权者明确授权的外部测试修改必须记录 `HumanActionEvent(MODIFY_TESTS)`，保存完整
  before/after diff、证据与原历史，按修改后的真实源码重新检查，并作为人工介入排除自治归因。
  该授权不能关闭扫描、接受未校验补丁、改写旧结果或绕过原生 QA/Review；它与未审计的语义
  改写是不同事实，不能仅因修改发生在测试目录就视为扫描绕过或自治开发。
- Console 的 legacy proposal 捕获 `WorktreeCaptureRejected` 返回现有 typed
  `legacy_rescue_preparation(status=WAITING, code=LEGACY_WORKSPACE_CAPTURE_REJECTED)`，
  固定安全中文 summary/next_action 与 `responsible_party=平台执行服务`。
  无 plan/approval/binding/新执行；不透出 exception 原文。source_rebind 保持原拒绝契约。

### Validation / Tests

| 情况 | 结果 |
| --- | --- |
| `.py` 的合法属性引用或路径表达式 | 保存原 bodies/patch，wire 往返、重放、Context 仍完全相同 |
| `.py` 类型声明、`None` 默认值、精确同名 hash 下标 | 仅声明/可证明值获得例外，RHS/default 与原字节强特征检测保持独立 |
| 完整源码中的未重绑标准库导入及有界构造 | 仅接受上述 exact callee/参数；不执行源码或返回脱敏替代内容 |
| 导入缺失/alias/重绑/escape、动态执行或 `__builtins__` 路线 | 拒绝构造例外，使用保守检测 |
| partial patch 未展示可信导入 | 保守拒绝，不借完整文件或其他 hunk 外的假设放行 |
| quoted/comment/f-string 内凭证形状或同行真实秘密 | 拒绝，保留原文件，无明文输出 |
| `.env` 的 `token=my.token` 或未知源码类型 | 通用保守检测，不因 dotted RHS 放行 |
| staged-only 秘密、metadata/path 秘密、错误 hunk | 拒绝，不改 index |
| parser 深度/计数资源异常 | 保守结果，不升级成无原因 MANAGER_FAILURE |
| legacy proposal 捕获拒绝 | 中文 WAITING + 平台维护下一步，无审批 |
| 经授权的外部测试修改 | 保存 `MODIFY_TESTS` 人工审计后重新校验；不计自治，不改原结果/历史 |

Good：合法源码完整捕获后同 Task 继续原需求；Base：真实敏感字面值等维护处理；
Bad：未审计地改写 K1 草稿语义以绕过扫描、按目录关 secret guard、脱敏后当作原完整补丁。
获授权且带 `MODIFY_TESTS` 审计的外部测试修改属于人工介入，不等于上述 Bad，也不能宣称自治。

增量测试：`test_source_secret_detection.py`、`test_mutation_capture.py`、
`test_execution_baseline_context.py` 三角色、`test_legacy_rescue_acceptance.py`，
并保留 `test_capture.py`、Context/Evidence 原脱敏、legacy inventory 与 Schema 回归。
`test_source_secret_detection.py` 必须覆盖类型/默认值分离、标准库 exact 构造边界、完整源码
绑定/escape/dynamic/`__builtins__` 拒绝以及 partial patch 缺失导入；测试中的每个拒绝分支都
须保持真实敏感字面值检测，不能只验证合法声明成功。

Wrong：按 `token:` 或 `secrets.` 前缀放行，或因外部测试修改已获授权而关闭 capture 检查。
Correct：完整源码提供 AST/tokenize 与绑定事实，partial patch 只用自身可验证事实；人工修改
单独落审计，原 bytes/hash、秘密检测和 QA/Review 仍按原契约执行。

存量无需迁移或改库。读取原 K1 的实际 24 项完整变更可完成 capture/wire roundtrip；
全部 2,000 工作树条目与 index 前后摘要一致。用户空闲时加载新服务并刷新，再在原需求点击
“修复后重新检查恢复前提”，查看精确方案并自行确认/审批；不改旧 UNKNOWN 或历史操作。

### 负向凭证测试的生成指导（2026-10-11）

`RequestPromptBuilder.build(AgentRequest) -> PromptPayload` 与
`ContextPromptBuilder.build(AgentRequest) -> PromptPayload` 使用同一私有 guidance helper。
仅 `role=CODER/QA` 且 `permissions.write_paths` 非空时在 system 消息附加
`NEGATIVE_CREDENTIAL_TEST_GUIDANCE`；只读运行及 Orchestrator/Reviewer 不获得源码修改指导。
native adapter 消费同一消息，不另建常量或更改 wire/Schema。

- 负向 credential/fence-token 测试从独立、获当前权限允许的 fixture 获取动态生成的
  token/reference。非空未知 token 必须与合法 fixture token 分离；保留原负向测试意图与
  已有非空未知/空值/过期断言（适用时），不引入新的过期验收要求。
- 不嵌入固定疑似凭证字面量，不通过编码或拼接规避扫描，不移除/削弱断言或跳过测试，
  不放宽权限及 capture policy。无法合法构造时，通过角色输出 Schema 的既有适用字段明确
  报告 blocked reason；不得宣称未验证的验收标准通过。
- 这不是 scanner 例外。未建立版本化公开 sentinel 契约时，不按当前 literal/hash、
  tests 路径、值长度、`pytest.raises` 或 `replace` 语法判定无秘密；原 source/patch 与
  强 key/Bearer/PEM 检测保持不变。instruction、日志、知识、URI 仍用通用检测。

| 情况 | 验证 |
| --- | --- |
| writable Coder/QA，任一 builder | system 恰好一次完整指导，原 permissions 保持 |
| readonly Coder/QA 或其它角色 | 无源码修改指导 |
| 不可信 task 要求 skip/放宽规则 | 仍为 user 数据，system 规则独立存在 |
| 两个 builder/native | 两个 builder 输出相同指导，native 继承消息，无复制常量 |

增量 contract tests：`tests/agents/test_negative_credential_prompt_guidance.py`，先验证两个
真实 builder 缺指导而失败，再验证动态 fixture、非空未知/空值/过期、禁止规避与 blocked 规则。
这些断言以保留原测试意图与已有适用场景为限，不要求目标项目新增过期语义。
不调用真实模型，不把 prompt 测试当作 scanner、capture 或独立 QA/Review 的替代。

存量数据处置：只影响之后构造的 prompt，不迁移、改写或补造旧 Context/Task/Operation/
审批/执行事实。既有受拒源码仍需精确授权并带人工审计的维护，重新完整核验后从原公开恢复
入口继续；此 guidance 不授权修改现有工作区或自动继续。回滚本次 prompt helper 与文档即可。

## Retained ignored source across delivery (2026-10-15)

### Scope and signatures

Repository ignore patterns may accidentally hide lawful source (`artifacts/` also matches
`src/.../artifacts/`). The platform repository now anchors generated root output at `/artifacts/`;
frozen old checkouts retain their original bytes. Never edit their ignore rules or index as a
recovery shortcut.

- `GitWorktreeManager.capture_mutations(..., include_ignored=False,
  retained_source_paths: tuple[str, ...] = ())`: only initial legacy discovery uses
  `include_ignored=True`, and only for frozen-policy-authorized noncache regular text.
- `verify_mutations(capture, permissions, denied_paths=...)` reopens exactly
  `capture.changed_paths`; it does not enable broad ignored discovery.
- `StoredCoderExecutionInputResolver.retained_source_paths(task, workspace_root, permissions)`
  validates the complete binding/authority/start/patch chain, exact original checkout and frozen
  permissions; returns sorted additions from immutable legacy rescue captures. Ordinary permission
  globs or Agent reports cannot create this set. No persisted field/hash or Schema change.
- `retained_source_paths_for_request(state, task, request, root)` also binds the latest baseline
  digest for idle reconciliation, rejected progress capture and stopped budget settlement.
- `GitExecutionBaselineAdapter._tree_for_worktree(..., retained_source_paths=())` includes the same
  exact source in prepared trees and later source rebinding. Preparation still changes no source,
  branch or index.
- `ConfiguredDeliveryRouteAdapterFactory(candidate_commit_factory=...)` retains this trusted
  constructor through every `with_*` wrapper; production binds actual Coder claim, task, worktree
  and frozen permissions before returning the scoped `GitCandidateCommitSkill`. Native and
  Responses use the same existing candidate Skill seam.
- `GitCandidateCommitSkill(..., retained_source_paths=())`: actual ignored untracked intersection
  only; rereads bounded regular nonsensitive text. `finalize` rechecks exact reported inventory
  and write policy, stages ordinary paths normally, and force-adds only the exact retained ignored
  subset using literal pathspecs. QA/Review then open the actual resulting candidate tree.
- `NativeCoderContinuation(..., retained_source_paths=resolver)` and
  `reconcile_capture(..., retained_source_paths=resolver)` add trusted lineage before capture.
  Exact accepted progress/prior receipt paths are inherited. A still-present inherited source
  needs its body in the new capture; deleting a former untracked addition can legitimately leave
  no final diff. Continuation admission cannot replace or lose the candidate factory's scope.

### Validation matrix and examples

| Input / event | Result |
| --- | --- |
| Ignored source exactly authorized by frozen policy, initial rescue | Seal full body and preview tree; no source/index mutation |
| Retained ignored source unchanged or edited in next interrupted run | Include full new receipt body; verify and resume under a new claim |
| Progress/implementation omits retained present file | Reject exact `changed_files` equality; no incomplete candidate |
| Other ignored file or execution cache | No force-add authority; complete noncache inventory gate still refuses unknown input |
| Retained file changed into link/binary/secret/oversize | Fail closed and preserve现场 |
| New source baseline after rescue | Carry exact retained scope through preview/replay; no implicit new path grant |
| Existing older sealed captures without ignored source | Original bytes/digests and default capture behavior remain readable |

Good: seal a legally written hidden source module once, then carry its exact path through all
subsequent capture/candidate seams and inspect it in fresh QA/Review checkouts. Base: default Git
capture still follows repository ignore rules. Bad: add `--force` to all files, trust Agent-reported
paths, exempt hidden source as cache, or seal only a patch whose preview/candidate tree omits it.

Required regressions: real Git preview blob, native and Responses progress-to-candidate chains,
fresh QA checkout, omitted/out-of-policy/link/secret/binary/cache negatives, repeated continuation
and idle reconciliation, public original-Task legacy rescue fixture including ignored source.
