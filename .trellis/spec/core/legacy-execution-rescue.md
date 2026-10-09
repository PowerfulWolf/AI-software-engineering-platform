# Legacy execution rescue

## Scope / trigger
Only a nonterminal local native Coder invocation with a real exact invocation-start and historical
claim but genuinely missing final outcome and original capture/stop ledger. This is a new
engineering disposition, never reconstruction of the old execution.

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

This survey is **not** a historical process-stop proof. A trusted human with ENGINEERING duty
supplies the missing facts by confirming the original invocation always ran on the same local
computer/account, was never moved or remote, and the original invocation **and all its derived
tools** have actually ended and cannot modify the workspace again. They accept UNKNOWN and
authorize preserved-draft execution from remaining work allowance. Without that exact declaration
no machine EngineeringAdmission may continue. Persist it in immutable authority and
HumanActionEvent(SUPPLY_EVIDENCE) with the authority URI; preserve old reboot event bytes/notes.

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

## Validation matrix
| Case | Behavior |
| --- | --- |
| OS boot before/equal original start | Current local survey + new exact engineering cessation declaration |
| Unreadable OS identity or incomplete survey / live execution | WAITING explanation, no plan or new invocation |
| Original final result now exists | Reject rescue; use original result replay |
| Missing original claim/start or nonlocal execution | Reject; no new invocation |
| Rescue authorization without exact same-device attestation | Reject before queue/source effects |
| Platform policy admission or changed source/input mode | Reject; explicit engineering decision required |
| Dirty/protected/ignored/staged drift or incomplete body | Preserve full现场; no reset/clear |
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
  sandbox/apply/default prompt 和包装路线保守阻塞。不能用四个子命令白名单放行未知 CLI。
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

- 仅语法明确的 single-name 对象同名字段引用，或 single-name `/` 带路径符号的普通固定字符串
  能获得源码例外。任意 identifier、未知 dotted value、函数调用、下标或插值不获得例外。
  路径字符串也必须通过通用检测。
- 字符串、注释、f-string（含嵌套及三引号）和 t-string 全 span 均不获得例外；强特征
  OpenAI/AWS/GitHub key、Bearer 和 PEM 独立检查整个原正文，不因 span 替换而丢失。
- AST/tokenize 的未知语法及资源限制使用保守结果，不执行源码。span 游标按位置单调移动，
  不在每次 assignment 上线性遍历所有字符串。
- v2 working/staged patch、完整 body、CapturedMutations、baseline replay 和 required execution
  Context 使用同一入口。Context 的 instructions 仍用通用 redactor；只有已绑定完整 patch
  用源码检查，任何 body/patch 均保持 byte-for-byte、SHA 和当前 index/HEAD/branch。
- v1 recovery、普通日志、URI、知识和 Evidence 的 `redact_text` 不变，其他语言和未知配置仍保守。
  不按 `src/**`、`tests/**` 或调用者提供的“安全”标记豁免。
- Console 的 legacy proposal 捕获 `WorktreeCaptureRejected` 返回现有 typed
  `legacy_rescue_preparation(status=WAITING, code=LEGACY_WORKSPACE_CAPTURE_REJECTED)`，
  固定安全中文 summary/next_action 与 `responsible_party=平台执行服务`。
  无 plan/approval/binding/新执行；不透出 exception 原文。source_rebind 保持原拒绝契约。

### Validation / Tests

| 情况 | 结果 |
| --- | --- |
| `.py` 的合法属性引用或路径表达式 | 保存原 bodies/patch，wire 往返、重放、Context 仍完全相同 |
| quoted/comment/f-string 内凭证形状或同行真实秘密 | 拒绝，保留原文件，无明文输出 |
| `.env` 的 `token=my.token` 或未知源码类型 | 通用保守检测，不因 dotted RHS 放行 |
| staged-only 秘密、metadata/path 秘密、错误 hunk | 拒绝，不改 index |
| parser 深度/计数资源异常 | 保守结果，不升级成无原因 MANAGER_FAILURE |
| legacy proposal 捕获拒绝 | 中文 WAITING + 平台维护下一步，无审批 |

Good：合法源码完整捕获后同 Task 继续原需求；Base：真实敏感字面值等维护处理；
Bad：改 K1 草稿以绕过扫描、按目录关 secret guard、脱敏后当作原完整补丁。

增量测试：`test_source_secret_detection.py`、`test_mutation_capture.py`、
`test_execution_baseline_context.py` 三角色、`test_legacy_rescue_acceptance.py`，
并保留 `test_capture.py`、Context/Evidence 原脱敏、legacy inventory 与 Schema 回归。

存量无需迁移或改库。读取原 K1 的实际 24 项完整变更可完成 capture/wire roundtrip；
全部 2,000 工作树条目与 index 前后摘要一致。用户空闲时加载新服务并刷新，再在原需求点击
“修复后重新检查恢复前提”，查看精确方案并自行确认/审批；不改旧 UNKNOWN 或历史操作。
