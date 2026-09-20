# 多目录联合交付契约

## 1. Scope / Trigger

适用于 `multi_directory/`、Host/CLI、批准投影、候选集合及恢复。入口在一个已选择的 Project 中接受
1–32 个非相邻目录，不要求共同父目录。一个 Git 仓库只形成一个 execution unit；保留用户所选模块
目录的写入上界。联合事实保存在
`<platform_root>/projects/<project_id>/requirements/<delivery_multi_id>/`，各 Repository 事实放在
同一 Project 的 `repositories/<repository_id>/`。Agent 归唯一 Team，代码不复制、不污染。

## 2. Signatures

```text
ase request create ABSOLUTE_DIR... --name NAME
ase request discuss DELIVERY_ID --checkpoint SHA256 --message TEXT
ase request approve DELIVERY_ID --checkpoint SHA256 [--approval-reference REF]
ase request status DELIVERY_ID
ase request resume DELIVERY_ID
```

`TeamHost.requirement_entry() -> JointDeliveryService` 装配生产后端。
`create(CreateRequirement) / reply(ReplyToProduct) / approve(ApproveProductSpec)
/ resume(ResumeProjectDelivery) / status(str)` 均返回 `JointDeliveryResult(checkpoint=...)`。
`ReplyToProduct` 接受可为空的 `message` 和最多 4 个 `screenshot_ids`，但两者不能同时为空。
`RequirementAttachmentStore.put/get/source_path` 管理 Project Requirement sidecar 中的截图。
旧 `ase project start DIR... --requirement TEXT` 兼容：单根目录走原生、多目录走联合服务；
单仓模块目录应使用 `request create`，由 scope discovery 归并为真实仓库根。

## 3. Contracts

`DirectoryScope → 全部 PrepareProjectResult → JointProductSpec → exact human approval
→ JointTechnicalDesign → JointExecutionPlan → per-repository delivery → integration evidence`。
多目录不是多个互不相关的 Product 会话。子仓库 Product/Design/Plan 是已批准联合事实的确定性
投影，不重新询问用户、不重新生成需求。每个子 Task 仍串行 Coder → QA → Reviewer。

- `scope.require_git_baselines(DirectoryScope) -> None` 在 intake journal 写入前检查全部 unit；
  任一 `base_revision=None` 抛 `RequirementGitBaselineRequired`，区分非 Git、没有有效 HEAD
  和旧需求未冻结基线。校验只读，不初始化 Git、补提交或调用模型。
- 历史 PREPARING/null baseline 的 `status()` 返回已验证原 checkpoint，不 reconcile、不要求
  源码仍存在；`resume()` 在 reconcile/prepare 前执行同一 baseline guard。修好源码后重新创建
  Requirement，新的基线参与新 identity，旧 checkpoint/Operation 不重写。
- Git 前置条件必须在 preparation 的 `_save()` 前校验：required nullable `base_revision`
  被 `to_wire(exclude_none=True)` 省略会提前触发 ValidationError，超过 Console 的摘要长度上限
  后掩盖原始问题。不得靠放宽摘要长度、伪造 revision 或修改通用序列化修复。

- create 准备所有目录后停在 READY_FOR_DISCUSSION，不调用模型。同名+同 Project+同 scope（含
  base SHA）幂等恢复；新需求使用新名称。dialogue、product_spec、approval、design、plan、children、
  integration、attempts 和 next_action 都保存在带 sequence/前后 SHA 的 JointCheckpoint。
- 截图先作为不可变 `RequirementScreenshot` 存入
  `requirements/<delivery_id>/attachments/<attachment_id>/`；ID 绑定 Project、Delivery、文件名和
  内容 digest。Dialogue 保存 manifest 而不是宿主临时路径。Product 调用时平台重新验证 manifest、
  source digest 和 owner lineage，再将真实路径作为 provider image input；Designer/Planner 不接收图片。
- 单次回复最多 4 张、单张最多 10 MB、整个 Product 对话最多 12 张；支持 PNG/JPEG/WebP。
  相同来源重传幂等返回原 identity，时间戳不参与来源冲突判断。
- `reply` 在追加用户 Dialogue 前必须先执行 Team binding 与 backend reconcile preflight；若任一
  Requirement retained baseline worktree、已准备事实或知识选择发生漂移，不得追加 checkpoint、
  Dialogue，也不得调用 Product Agent。配置的主 checkout 后续前进或变脏不属于旧 Requirement
  漂移。成功写入 `PRODUCT_DISCOVERY` 后，`_advance` 在调用模型前再次
  reconcile，作为 validation-to-execution fence，不能用前置 preflight 替换该栅栏。
- `resume` 将 `BLOCKED` 重新排入 `DELIVERING` 前也必须 reconcile；漂移时保留原 BLOCKED
  checkpoint，不能先持久化伪恢复状态。`start/create` 的首次 PREPARING intake 是用于崩溃恢复的
  明确 commit point，不受该规则影响。
- 主状态链：PREPARING → READY_FOR_DISCUSSION → PRODUCT_DISCOVERY → WAITING_PRODUCT_APPROVAL
  → DESIGNING → PLANNING → DELIVERING → INTEGRATING → DONE；另有 WAITING_PRODUCT_REPLY、
  WAITING_HUMAN 和 BLOCKED。Task 的原生状态机不变。
- DerivedStageInputs 从已批准联合文档选取全局 requirement 子集，映射为原生局部 req/ac IDs；
  `joint-approval:<parent-id>:<approval-digest>:<unit-id>` 只验证精确父批准，不是 Agent 自批。
- 子仓 `joint.approved_context` 包含联合方案、接口、验收及已完成声明依赖的候选事实；原生
  dispatch、Task、worktree、独立 QA/Review 和 Artifact/Evidence 守卫不得绕过。
- integration 使用全部 write candidate SHA 和 reference-only base SHA，在外置 detached worktrees
  执行。每条接口至少一个 check 同时消费 producer 和全部 consumers；证据绑定精确 plan/candidate set。
- 测试 argv 必须同时匹配 RepositoryProfile allowlist 和支持的测试前缀，禁止 shell/inline code、
  install/deploy、inspection 替代测试、常见 help/collect-only/skip-tests 参数；明确零测试的成功退出拒绝。
- cwd 是 check.unit_id 的候选根；环境包含 PATH、PYTHONDONTWRITEBYTECODE 和
  `ASE_UNIT_<uppercase 16hex unit suffix>`（对应候选路径）。直接 Python/pytest 命令优先使用目标
  仓库既有 `.venv/bin`，并仅把候选 `src`/根目录放入 PYTHONPATH；不继承 Host PYTHONPATH 或
  secrets，不自动安装依赖。输出脱敏、限长、有超时。
- 每条命令后检查全部候选 HEAD/clean；仅清理未变化 worktree，保留异常现场。这是应用 guard，
  不替代 OS/container sandbox；只运行可信项目代码，测试的业务充分性仍依赖设计和独立 QA/Review。

## 4. Validation & Error Matrix

- 输入必须是存在的绝对目录；规范化别名、重复和父子选择，同一仓库合并 scope。
- 所有目录先发现/编译规范；任何规范冲突阻止 Product，交由人类处理。
- Product ID/digest 精确批准；旧 checkpoint 的 reply/approve 不得改变新事实。
- Requirement 准备后的配置 Repository HEAD 可以正常前进；旧 Requirement 必须继续读取其 retained
  baseline worktree，并让原生子 Task 从 `DirectoryUnit.base_revision` 创建 Coder worktree。只有该
  retained baseline 的 commit、worktree identity、HEAD 或 clean 状态不可验证时，reply 才返回 typed
  `RequirementSourceRevisionDrift`；journal current checkpoint、Dialogue 与模型调用次数保持不变。
- 空文字只有在提供有效截图时允许；附件必须属于 exact Project/Delivery，stale checkpoint、已进入
  Design/Delivery 的需求、缺失/篡改/foreign attachment 均失败关闭且不调用 Product。
- Design 必须划分全部 unit 为 write 或 reference-only；覆盖全部产品 requirement IDs；
  component paths 不得扩大 selected scopes。接口的 producer/consumer 必须属于本次输入。
- Planner 只给有界串行顺序，不引入通用 DAG；依赖不得指向尚未完成的 write unit。
- 各仓库候选、QA/Review、子 checkpoint 必须与联合 spec/design/plan 绑定；partial DONE
  不等于联合 DONE。集成验收引用完整 candidate set，在外置 detached worktrees 执行受控命令。
- 父需求中的 child checkpoint 是已提交观察值，子交付可在父 checkpoint 之后继续追加。读取和恢复
  必须确认该 child 是同一条已验证原生哈希链中的精确历史前缀；不得要求它等于最新 child，也不得
  接受缺失、替换、超前或跨交付记录。只有 DONE child 仍要求父记录与当前原生候选完全一致。
- 没有可执行的联合验收、命令失败、仓库不支持或事实漂移均不得宣称 DONE。
- journal 使用不可变 hash-chain、CAS 和进程锁；重放已持久化完成阶段不重复模型调用或交付。
- 原生子交付完成、父记录未保存的崩溃窗口由确定性子 ID 恢复，复用候选，不再次运行 Coder。
- 已有 child 的 `deliver(checkpoint, unit_id)` 必须经 `delivery_runtime()` 重建当前原生
  checkpoint 精确绑定的 preparation/source revision，再调用原生 `status()`。恢复可能已经采用
  新 preparation，不能重新用父需求最初的 preparation 调用 `start()`。DONE 观察值直接追加回
  父 journal 并进入候选集验收，不重跑该 child 的 Coder/QA/Reviewer；BLOCKED/FAILED 仍保留，
  不在此入口绕过恢复审批。没有 child 观察值时继续使用确定性 `start()` 恢复首次派发窗口。
- Product 最多 20 次、Design/Plan/Integration 各 3 次调用，调用前记录尝试。模型响应到文档落盘
  的窗口可能重复计费；崩溃后的测试可能重跑，不承诺 exactly-once。
- 子仓 BLOCKED/FAILED 或联合测试非零：保留候选与证据，父需求 BLOCKED。当前 checkout、规范或
  知识变化只影响新需求；旧需求继续使用已封存准备事实和代码基线。不自动扩大已批准范围或引入修复
  DAG。旧需求自己的 retained baseline 漂移必须 fail closed，不能覆盖历史。
- 联合验收命令无法启动、超时或报告零测试时，Production backend 必须把稳定的失败类别封存为
  `CommandResult`；不得让 Manager facade 把异常降级为无证据的 `MANAGER_FAILURE`。父需求随后进入
  `BLOCKED`，失败命令和候选集合仍可读。
- `BLOCKED` 且带失败 `integration` evidence 的继续交付是唯一的联合计划替代入口：平台追加一个
  保留旧 plan/evidence 的 `PLANNING` checkpoint，Planner 在原有有界预算内生成完整新计划。Journal
  只允许这个精确前置条件清空当前 plan；旧计划永远保留在历史中。新计划通过所有验证后，已完成
  child 不重跑，父需求重新进入 `INTEGRATING`。
- 重规划 checkpoint 在 Planner 运行前可能暂时为 `PLANNING + plan=null`，但仍保留已完成 child。
  该窗口的 reconcile 必须直接读取并校验 child 原生 journal 的精确历史前缀；不得构造要求当前
  plan 的 `DerivedStageInputs`，也不得因此让只读 status 失败。只有新 plan 封存后，后续 child
  runtime 才重新绑定新的联合 plan。
- 不自动 merge/push，不承诺跨仓库原子提交；dirty worktree 保留，不强制删除。

## 5. Good / Base / Bad Cases

- Git intake Good/Base：有提交的仓库或模块继续准备；无 Git/无提交时明确拒绝且不创建 journal。
  Bad：先准备部分仓库再检查基线，或 status 为查看旧失败记录而依赖失效的源码路径。
- Good：后端与非相邻前端，一次批准、独立候选、读完整候选集的联合测试通过后 DONE。
- Base：一个目录使用同一 request 入口；纯文字 Product 对话保持兼容；参考目录不创建无意义 Coder Task。
- Bad：分别发起产品会话、让 Product/Coder 读取不断前进的主 checkout、把截图转成未校验路径塞进
  prompt、先保存用户回复再检查 retained baseline，或用两个单仓 PASS 冒充接口兼容验证。
- Recovery Good：父 child 仍指向旧 BLOCKED 前缀，而原生链已基于另一个获批 preparation 完成；
  `reconcile` 和 `deliver` 使用同一 `delivery_runtime`，取回最新 DONE，父继续 integration。
  Recovery Bad：preflight 用当前 child runtime 通过后，execution 又从父 preparation 新建 runtime，
  将合法恢复误报为 `delivery preparation checkpoint drifted`。
- Integration Recovery Good：测试可执行文件缺失时先封存 `command could not start` 和候选集合，
  父需求显示 BLOCKED；用户继续后 Planner 产生引用候选中已有测试的新计划，子仓库仍保持原
  Reviewer candidate。
- Integration Recovery Bad：捕获异常后直接重跑同一错误 argv、覆盖旧 plan/evidence，或把成功但零
  测试的退出当作联合 PASS。

## 6. Tests Required

`tests/web_console/test_git_baseline.py` 必须通过真实 production preparation/Console seam 验证
错误码、目录、恢复指引、持久化 Operation 的 Schema，以及非 Git/无提交/混合目录/长路径/
正常仓库和模块。历史 Continue 使用 prepare/reconcile 失败哨兵，断言原 checkpoint 字节不变，
补提交后可创建 READY_FOR_DISCUSSION 新需求。`test_requirement_journal_is_project_scoped`
继续验证源目录缺失时 status 仍可读取历史；未知长异常仍使用通用安全摘要。

多目录/同仓库多模块/非相邻目录、重复和 symlink、越界写路径、reference-only、stale approval、
重新启动恢复、候选集漂移、部分成功、失败集成验收、单目录入口回归；生产桥接另用离线
structured provider + 真实 Git worktree + MySQL 验证，不消耗真实模型额度。

`test_joint_scope_recovery_targets_current_preparation_after_main_advances` 覆盖恢复再次中断与恢复
完成两种结果。完成分支必须证明父交付 DONE、集成证据存在、采用获批的新 preparation，且只有
未完成仓库运行角色。重复 resume 保留相同候选和 checkpoint，不增加角色调用。真实运行检查
应比较父/子 journal 前后哈希，只观察已完成 child，不代替用户执行联合集成。

`test_requirement_product_keeps_its_source_baseline_after_checkout_advances` 必须断言主 checkout 前进后
旧 Requirement 仍可继续、Product 收到 detached baseline root 且读取旧内容。
`test_requirement_rejects_a_modified_retained_source_baseline` 必须断言 baseline worktree 被修改时
reconcile fail closed。reply/reconcile 拒绝时 current checkpoint 不得增加 Dialogue 或调用模型。

对应 `test_directory_scope.py`、`test_joint_contracts.py`、`test_team_workspace.py`、
`test_team_host.py`、`test_requirement_attachments.py` 与 `tests/e2e/test_joint_delivery.py`。五份 joint/request canonical Schema
必须与 Pydantic 完全一致。全量 MySQL 回归不可由独立 E2E 或 skipped suite 替代。

联合验收恢复还必须覆盖：启动失败、超时、非零退出、零测试成功、失败 evidence 脱敏、
`BLOCKED + integration evidence → PLANNING` 的唯一计划替代，以及重规划后不重复执行 DONE child。

## 7. Wrong vs Correct

Wrong：`for root in roots: native.start(root, same_requirement)`，各自产品设计后只检查子任务 DONE。

Correct：联合 Product + 人工批准 → 联合 Design/Plan → 确定性原生投影 → 各仓独立 QA/Review
→ pinned integration evidence → joint DONE。

Wrong：`client.complete(input_payload={"screenshot_path": browser_text})`。

Correct：`attachment_store.get(...) → digest/owner validation → client.complete(input_images=...)`。

Wrong：`save(user_dialogue) → reconcile() → Product`，漂移时留下伪成功的用户消息 checkpoint。

Correct：`validate command → reconcile preflight → save(user_dialogue) → reconcile fence → Product`；
任一 reconcile 失败都不能调用模型，前置失败还必须保持 journal 完全不变。

## Scenario: Requirement-owned source baselines

### 1. Scope / Trigger

同一 Repository 可以并行存在多个 Requirement，配置的主 checkout 可以在任一 Requirement 交付期间
前进。触发范围包括联合 Product/Designer/Planner 代码读取、原生子 Task dispatch 与恢复校验。

### 2. Signatures

```python
JointBackend.client(checkpoint: JointCheckpoint, role: TeamRole) -> StructuredModelClient
ConfiguredStructuredClientFactory.for_projects(
    repository_roots: tuple[Path, ...], role: TeamRole
) -> StructuredModelClient
ProductionProjectDeliveryBackend(
    *, frozen_preparation: PrepareProjectResult | None,
    frozen_source_revision: str | None,
)
```

Codex CLI 的第一个 baseline root 通过 `-C` 绑定，其余 baseline roots 通过重复的 `--add-dir` 只读挂载。

### 3. Contracts

- intake 在读取准备事实前后都要求配置 checkout clean 且 HEAD 等于 `DirectoryUnit.base_revision`。
- 每个 Requirement/Repository 在
  `<platform_root>/worktrees/requirements/<delivery_id>/<unit_id>/.../reviewer-attempt-01`
  拥有确定性 detached baseline；不同 Requirement 不共享该目录。
- Product/Designer/首次 Planner 只读取这些 retained baselines；保留 DONE child 的联合验收
  重规划读取候选 SHA 对应的只读 worktree，reference-only unit 仍读取原 baseline。
  知识、规范、RepositoryProfile 和
  `PrepareProjectResult` 使用 Requirement checkpoint 中已封存的版本。
- 原生子 Task 的 `Task.base_ref` 必须等于该 unit 的 `base_revision`，不能在 dispatch 时重新读取主
  checkout HEAD。Coder 仍拥有独立可写 Task branch/worktree；QA/Reviewer 仍验证 candidate SHA。
- v0.1 不自动 merge。最终 Review 后由人类/后续发布边界把 candidate 合入最新目标分支并解决冲突。

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| 主 checkout 在 Requirement 创建后新增提交 | 旧 Requirement 继续，读取旧 baseline；新 Requirement 读取新 HEAD |
| 两个 Requirement 同时修改同一 Repository | 使用不同 baseline/Task worktree；互不改写；最终 merge 处理冲突 |
| 主 checkout 在旧 Requirement 运行时 dirty | 不影响旧 retained baseline；新 intake 仍拒绝 dirty source |
| baseline worktree identity/HEAD/clean 漂移 | `RequirementSourceRevisionDrift`；保留现场，不调用模型/dispatch |
| recorded commit 不可解析 | `RequirementSourceRevisionDrift`；要求恢复 commit/worktree |
| frozen preparation 与 unit revision 不一致 | fail closed；不得回退到当前准备事实 |

### 5. Good / Base / Bad Cases

- Good：需求 A 从 commit A 编码；A 合入 main 后需求 B 仍从自己的 commit B 继续，最终合并时处理冲突。
- Base：单 Requirement 单 Repository 仍使用一份 detached baseline 和一个独立 Coder worktree。
- Bad：每次 reply/resume/dispatch 都读取主 checkout HEAD，并把正常分支更新误判为 Requirement 漂移。

### 6. Tests Required

- Unit：Codex structured command 包含精确 `-C`/`--add-dir` baseline roots。
- Manager：主 checkout 前进后旧 Product 对话读取旧内容；baseline dirty 时拒绝。
- MySQL E2E：创建旧 Requirement、推进 main、创建新 Requirement，再完成旧 Requirement；每个 candidate
  的 parent commit 等于旧 unit `base_revision`，主 checkout 内容不被回退或污染。

### 7. Wrong vs Correct

```python
# Wrong: dispatch/read identity follows mutable integration checkout.
task_base = clean_git_head(configured_checkout)
product = clients.for_project(configured_checkout, TeamRole.PRODUCT)

# Correct: both identities come from the immutable Requirement checkpoint.
task_base = unit.base_revision
product = clients.for_projects(requirement_baseline_roots, TeamRole.PRODUCT)
```

## 8. Planner coverage rejection feedback (T038)

Scope: semantic acceptance/write-unit omissions after JointExecutionPlan parsing, not provider,
authorization or arbitrary schema failures. `JointProductSpec.acceptance_ids() -> tuple[str, ...]`
is shared by the validator and model context. `_produce` supplies
`required_coverage.{acceptance_ids,write_unit_ids,interface_ids}` from approved Product/Design facts.
These context-only fields do not alter wire schemas or authorize new requirements.

`JointExecutionPlan.validate_for(...)` raises `PlanCoverageError` for missing acceptance/write
coverage. `JointDeliveryService` appends a PLANNING checkpoint with the rejected plan SHA and
safe missing IDs in `next_action`, then re-raises; `plan` remains absent. Only expected IDs generated
from trusted facts enter diagnostics, never provider prose, commands, raw output or secrets.
Resume preserves approval/Design, includes durable next_action, and spends the existing three-call
budget. It cannot auto-fill a model plan, produce a verdict, reset attempts or accept a partial plan.

| Case | Required behavior |
|---|---|
| One omitted acceptance or write unit | Reject; persist precise missing IDs + plan digest |
| Restart after rejection | Same feedback in next Planner input, preserved approval and budget |
| Corrected plan | Revalidate every guard, only then enter delivery |
| Three rejected plans | Next resume rejects before calling model |
| Unrelated schema/provider failure | Existing failure path; not reclassified or silently retried |

Good: durable rejection guides the second bounded model attempt. Base: valid first attempts are
unchanged. Bad: infer test coverage, silently add IDs, or retry without explaining omissions.
Wrong: catch every exception and pass raw error text to the model. Correct: catch only the dedicated
trusted coverage error, seal the diagnostic checkpoint, and preserve fail-closed behavior.

Regression: `tests/manager/test_joint_planner_feedback.py` exercises service + real journal
with deterministic models, restart, exact input IDs, preserved approval, strict rejection, and
attempt exhaustion. It does not claim live model success or independent QA/Review of feature code.

## 9. Exact integration command context (T039)

Scope: Planner context and `ProductionJointBackend.validate_plan` command preflight. General
RepositoryProfile commands are broader than integration tests; neither list alone grants execution.
`integration_commands.planner_command_policy() -> dict[str, object]` returns a fresh copy of
`test_prefixes`, `forbidden_options`, and the project-allowlist-intersection requirement.
`is_test_command(argv: tuple[str, ...]) -> bool` enforces those same immutable constants. No prefix
or flag behavior is widened. Planner receives this as `integration_command_policy`.

If the existing test-command predicate rejects a plan, backend raises `IntegrationCommandError`
with a one-based check index and argv SHA-256, not argv/check-name text. Service seals that safe
feedback and rejected-plan SHA in a new PLANNING checkpoint, leaves plan absent, then re-raises.
Resume sees the feedback and still uses the original three-call budget. Arbitrary policy/provider
exceptions are not caught and echoed. Canonical schemas and prior checkpoints are unchanged.

| Case | Result |
|---|---|
| Supported test prefix + project allowlist, no forbidden flag | Existing preflight continues |
| Build, lint, inspection, install or test-skip/help argv | Reject; never reinterpret as a test |
| Rejected command contains sensitive argument | Diagnostic stores hash/index only |
| Context consumer mutates returned list | Authoritative predicate remains unchanged |
| Valid new plan after rejection | Full preflight again, never a fabricated verdict |

Good: choose argv from the intersection of prepared commands and test policy. Base: valid first
plans unchanged. Bad: broaden the validator because a model selected a disallowed command.
Wrong: duplicate a partial prefix list in a prompt. Correct: derive context and enforcement from
one module and verify both with `test_integration_command_policy.py`. Service/journal feedback
regression is `test_command_rejection_is_safe_and_durable`.

## 10. Bounded Designer duplicate-consumer correction

### Scope / Trigger

Schema-valid JointTechnicalDesign with repeated interface consumers. This is a recoverable
model artifact rejection, not permission to normalize the model output or retry arbitrary errors.

### Signatures and contracts

`DesignInterfaceConsumersError(interface_index: int)` is a ValueError subtype raised by
`JointTechnicalDesign.validate_for(scope, product)` after interface scope membership checks.
`JointDeliveryService._advance` catches only this type, seals a DESIGNING checkpoint containing
the rejected design SHA and one-based interface index in `next_action`, then calls Designer again
within the existing three-call design budget. Every call spends an attempt before execution.
The invalid design remains absent; feedback never includes interface names, prose or raw output.
Approval, product and scope are unchanged. No wire fields, schemas or migration are introduced.
An interruption preserves the feedback and spent attempts. Exhaustion raises before another call;
the last DESIGNING checkpoint remains inspectable, with no accepted design or downstream Task.

### Validation & Error Matrix

| Case | Result |
|---|---|
| Repeated known consumers, then valid full design | Durable rejection; full validation before Planner |
| Three duplicate-consumer rejections | No fourth call, no plan/dispatch; preserve last diagnostic |
| Provider interruption during correction | Propagate; resume retains feedback and budget |
| Wrong ProductSpec digest, foreign unit, schema/provider error | No automatic retry |
| Proposed write-path rejection | Dedicated bounded feedback in section 11; scope never widened |
| Already accepted Design | Resume does not regenerate Design |

### Good / Base / Bad and tests

Good: Designer corrects the complete document using durable `next_action`; Base: first valid
design behaves as before; Bad: silently deduplicate consumers and approve the altered document.
`tests/manager/test_joint_designer_feedback.py` uses a deterministic provider and real
journal to assert exact rejection, correction before planning, preserved approval, interruption,
budget exhaustion/reopen, safe diagnostics, and no retry for unrelated violations.

Wrong: `except ValueError: retry()` or `consumers = tuple(set(consumers))`.
Correct: catch the dedicated safe diagnostic, append immutable feedback, spend the existing budget,
and revalidate the next complete artifact. Production delivery success still needs real QA/Review.

### Bug analysis

1. Root cause (B/D/E): semantic uniqueness is stricter than JSON shape; the service assumed a
   parsed design was semantically usable, and tests lacked rejection-to-correction coverage.
2. Prior fixes: Planner feedback did not cover Designer. This fix keeps that distinct boundary;
   it does not generalize Planner retries or treat provider failures as design errors.
3. Prevention: P0 typed safe diagnostic and durable correction loop DONE; P0 real-journal
   regression tests DONE; P1 audit other semantic validators for similarly safe feedback TODO.
4. Systematic expansion: other validation failures still fail closed. Add typed feedback only
   after defining the safe fields and call budget; never echo arbitrary exceptions.
5. Knowledge capture: this section records the executable contract and regression seam. This repo
   has no `src/templates/markdown/spec/` mirror to synchronize.

## 11. Designer write-path rejection feedback

Scope: a schema-valid design proposes a path rejected by `DirectoryUnit.permits`. Its predicate
is unchanged: noncanonical paths and true scope escapes both remain rejected. No automatic
normalization or expansion of selected directories is allowed.

Signature: `DesignWritePathsError(unit_index: int, component_index: int, path_index: int)`.
The validator supplies one-based positions, never raw paths or component names. The service seals
the rejected design digest and safe diagnostic in `next_action`, then requests a complete corrected
design using the same total three-call Designer budget as section 10. All guards run again.
Approval, selected scope, previous checkpoints, wire schemas and provider-failure behavior stay
unchanged. This error concerns a proposed artifact, not an executed unauthorized write.

| Input / event | Required behavior |
|---|---|
| `./src/file.py`, `src/`, `.`, absolute or traversal path | Reject, persist safe indices and correction rules |
| Canonical path outside selected module | Reject; never widen scope |
| Corrected complete design within scope | Revalidate before Planner |
| Three rejections or restart after exhaustion | No fourth call or child Task |
| Unrelated provider/lineage failure | Propagate, no catch-all retry |

Good: Designer regenerates an in-scope document; Base: valid first output is unchanged;
Bad: strip `../` or enlarge scope to make the output pass.
Wrong: echo arbitrary exception/path strings to the model. Correct: typed error with fixed text,
indices and rejected artifact digest, durable feedback, bounded calls.
Tests: `test_invalid_write_path_feedback_is_safe_and_bounded` covers five invalid path forms,
correction, strict rejection, exhaustion/restart, approval preservation and secret-free diagnostics;
existing scope/contract tests preserve module containment and schema parity.
Root cause (B/D): semantic path rejection lacked a safe service feedback contract. Consumer-only
repair did not cover this independent validator. Prevention is typed diagnostics plus service/journal
tests, not relaxing the validator. Other semantic failures remain fail-closed pending explicit contracts.

## Scenario: one audited supplemental integration attempt

### 1. Scope / Trigger

Three integration attempts were spent, failed command evidence remains, and every modified child
is DONE. This recovers infrastructure/plan failures after native Review; it does not approve code.

### 2. Signatures

`JointDeliveryResult.integration_retry_proposal: IntegrationRetryProposal | None` contains
`checkpoint_sha256`, reviewed child `candidates`, and `next_attempt=4`.
`resume(ResumeProjectDelivery(approved_plan_sha256=digest(proposal), approval_reference=...))`
appends `JointCheckpoint.integration_retry_approval` with the proposal, reference and timestamp.
Console exports `approval.kind=joint_integration` and the browser returns the exact digest through
the existing `CONTINUE_DELIVERY` approval seam.

### 3. Contracts

- Only BLOCKED/PLANNING + three spent attempts + failed integration evidence + all DONE children
  can propose this opportunity. Merely requesting the proposal writes nothing and calls no models.
- Exact digest approval is required; lock/CAS rejects stale proposals. The original three attempts,
  plan, evidence and child histories are never erased. Approval cannot be replaced or removed,
  candidate identities cannot change, and integration attempts cannot decrease afterwards.
- One extra execution raises the limit to four; it does not reset Planner's original three-call
  budget. A failed/interrupted fourth execution cannot automatically become a fifth. CLOSED remains
  closed, DONE remains immutable, and no native Coder/QA/Reviewer is re-executed.
- Planner recovery reads clean detached candidate worktrees for DONE children and the sealed baseline
  for reference-only units. It must preserve full acceptance/interface coverage and select actual
  candidate tests. No source edits, synthesized tests or relaxed command policies are permitted.
- `validate_plan` rejects explicit pytest `.py[::node]` selectors absent from the candidate tree or
  escaping the repository before accepting the replacement plan. `IntegrationCommandError` persists
  only safe reason/index/argv hash. Initial planning before implementation is unaffected.
- Existing Python tooling may be borrowed from the target repository's nonsymlink `.venv/bin`.
  Candidate paths, not the mutable main checkout, own cwd/imports. No credentials or auto-install.

### 4. Validation & Error Matrix

| Input | Result |
|---|---|
| Exhausted failed integration, exact reviewed children | Stable proposal, no execution |
| Stale proposal digest / candidate drift | Reject before approval or test execution |
| Exact human approval | Append audit checkpoint; at most attempt four |
| Fourth failure / repeated continue | Keep BLOCKED and evidence; no extra model/test run |
| Approval removal or attempt reset | Journal successor validation rejects |
| CLOSED resume | Remains CLOSED; explicit restart still required |
| Pytest file only on newer main or nonexistent | Reject plan with safe durable feedback |

### 5. Good / Base / Bad Cases

Good: repair environment, approve once, replan against reviewed candidates, verify integration.
Base: a request below the default budget follows existing bounded recovery.
Bad: clear counters or mark native/parent DONE to make the UI look successful.

### 6. Tests Required

`test_failed_integration_replans_without_redelivering_done_children` asserts proposal idempotency,
exact approval, retained history, success/failure, no fifth run and no counter reset.
`test_integration_uses_project_tooling_and_imports_candidate_sources` runs a real isolated command;
`test_integration_pytest_paths_are_bound_to_candidate` excludes newer-main/missing tests.
`test_joint_reader_preserves_child_ownership_through_integration_replanning` uses real Git/MySQL and
scripted providers to prove Planner candidate roots, full recovery, and read-only ownership.
Console/schema tests plus `ui.test.cjs` assert exact approval digest submission from PLANNING.

### 7. Wrong vs Correct

Wrong: edit `attempts.integration=0` in the production journal and repeat the same missing command.
Correct: retain facts, fix tooling/context, publish a candidate-bound proposal, record explicit
approval, then execute a bounded test through the unchanged evidence/verdict guards.

## 12. Requirement replacement, close/restart and logical retirement

### 1. Scope / Trigger

Applies when a browser user corrects the title or Repository scope of an unstarted Requirement, or
removes a Requirement before ProductSpec approval from the current Project inventory. Joint intake
identity includes title and scope, and
checkpoint intake fields are immutable, so an edit must publish a replacement rather than rewrite a
journal. Delete is visibility retirement, never evidence erasure.

### 2. Signatures

```python
class UpdateRequirement(DomainModel):
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    name: str
    repository_roots: tuple[NonEmptyStr, ...]
    submitted_at: AwareDatetime

class DeleteRequirement(DomainModel):
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    submitted_at: AwareDatetime

class CloseRequirement(DomainModel):
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest

class RestartRequirement(DomainModel):
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest

JointDeliveryService.update_requirement(UpdateRequirement) -> JointDeliveryResult
JointDeliveryService.delete_requirement(DeleteRequirement) -> JointDeliveryResult
JointDeliveryService.close_requirement(CloseRequirement) -> JointDeliveryResult
JointDeliveryService.restart_requirement(RestartRequirement) -> JointDeliveryResult
RequirementRetirementStore.retired_delivery_ids(JointJournal) -> frozenset[str]
```

The public storage contract is `schemas/requirement-retirement.schema.json` at
`<project>/requirements/retirement.json`.

### 3. Contracts

- Update accepts only exact `READY_FOR_DISCUSSION` checkpoints produced by named Requirement
  creation, with no initial requirement text, dialogue, ProductSpec, approval, Design, Plan, child or
  integration facts. Once Product discussion starts, correction requires a new Requirement.
- Delete accepts exact named Requirements in `READY_FOR_DISCUSSION`, `PRODUCT_DISCOVERY`,
  `WAITING_PRODUCT_REPLY` or `WAITING_PRODUCT_APPROVAL`, provided approval, Design, Plan, children
  and integration facts are absent. Unapproved ProductSpec and Dialogue are preserved in the retired
  journal. ProductSpec approval closes the deletion boundary.
- Update discovers and validates the new 1–32 directory scope, derives its normal content-addressed
  Delivery ID, creates/reopens that replacement through `_intake`, then retires the original. A
  replacement failure leaves the original visible. If this update created a partial replacement
  journal before preparation failed, the service logically retires that partial identity so it does
  not appear as a second current Requirement; its failure evidence is still preserved.
- Delete records `reason=deleted` and returns the original checkpoint; it never removes checkpoints,
  attachments, Repository sidecars or Git state.
- A BLOCKED close appends `CLOSED`. Restart accepts only the exact current `CLOSED` checkpoint and
  appends `BLOCKED`; it does not call a provider or resume work. The existing resume command remains
  the explicit execution boundary.
- Deletion of BLOCKED/CLOSED Requirements is allowed. Current read projections must remove the joint
  Requirement plus all child/native Tasks it owns, including Agent queue entries, while preserving
  their journals and sidecars for audit.
- The retirement record binds exact Team/Project manifest digests. Every entry binds the retired
  Delivery and its current checkpoint digest; a replacement entry additionally binds an existing
  replacement journal owned by the same Team/Project. The record is sorted, unique, digest-sealed,
  atomically replaced under a process lock and fsynced.
- Retrying the same logical retirement is idempotent even if `retired_at` differs. A changed reason,
  checkpoint or replacement identity is a conflict.
- Recreating the exact input of an explicitly deleted draft restores it. A draft superseded by edit
  cannot be silently reopened under the old identity.

### 4. Validation & Error Matrix

| Case | Required result |
|---|---|
| READY draft + exact digest + changed title/scope | create/reopen replacement, then retire original |
| READY draft + identical title/scope | reject; no journal or retirement mutation |
| Edit identity collides with a Requirement that already started Product discussion | reject while holding replacement lock; original remains visible |
| stale digest | `DeliveryCheckpointStale`; no replacement/retirement |
| Edit after Product discussion starts | reject; create a new Requirement instead |
| Delete during Product discussion or with an unapproved ProductSpec | retire current visibility; preserve Dialogue/ProductSpec history |
| Delete an active post-approval Requirement | reject; immutable approved lineage remains visible |
| BLOCKED close + exact digest | append CLOSED and keep visible under closed inventory |
| CLOSED restart + exact digest | append BLOCKED; wait for explicit continue |
| restart a non-CLOSED Requirement | reject without mutation |
| delete BLOCKED/CLOSED Requirement | retire parent and suppress all derived current-work projections |
| exact repeated delete/replace | return current retirement record; do not duplicate entry |
| different retirement for the same Delivery | reject conflict |
| retirement digest/owner/checkpoint drift | fail the read and command closed |
| replacement journal missing or foreign | fail closed; do not hide corruption |
| newly-created replacement preparation blocks/fails | original remains visible; partial replacement is retired, not erased |
| recreate exact deleted input | restore exact draft after normal intake validation |
| recreate superseded input | reject as superseded |

### 5. Good / Base / Bad Cases

- Good: rename an untouched draft; the replacement opens automatically while the original immutable
  checkpoint remains auditable.
- Base: delete an untouched draft or irrecoverable pre-approval Product discussion and remove it from
  current Project inventory/counts without erasing history.
- Bad: mutate `JointCheckpoint.title`, delete its directory, or hide a replacement record without
  proving the referenced replacement journal exists.

### 6. Tests Required

`tests/manager/test_requirement_retirement.py` covers replacement, logical delete, stale and stage
guards including pre-approval delete and post-approval rejection, idempotent retries, replacement
existence and tamper failure. Manager/schema tests assert
typed intent delegation and Python-to-JSON-Schema parity. Reader tests assert retired Requirements
leave the selected list, Project count, native Task projection and Agent queues without deleting the
source journal or Repository sidecar.

### 7. Wrong vs Correct

```python
# Wrong: change identity-bearing intake fields inside an existing hash chain.
checkpoint = checkpoint.model_copy(update={"title": new_name})

# Correct: publish the ordinary content-addressed replacement, then retire the old identity.
replacement = service.create(CreateRequirement(name=new_name, repository_roots=roots))
retirements.retire(
    old, reason="replaced", replacement_delivery_id=replacement.checkpoint.delivery_id
)
```

## Scenario: single-repository acceptance versus joint integration

### 1. Scope / Trigger

Applies after every modified native child is DONE. The number of selected repositories determines
the acceptance path; a one-repository Requirement is not a degenerate multi-repository integration.

### 2. Signatures

```python
class SingleRepositoryAcceptance(DomainModel):
    unit_id: UnitId
    child_checkpoint_sha256: Digest
    candidate_revision: NonEmptyStr
    product_spec_sha256: Digest
    acceptance_ids: tuple[NonEmptyStr, ...]
    native_evidence_references: tuple[NonEmptyStr, ...]

ProductionProjectDeliveryBackend.accepted_delivery_evidence(
    ProjectDeliveryCheckpoint,
) -> tuple[str, ...]
ProductionJointBackend.accept_single_repository(
    JointCheckpoint,
) -> SingleRepositoryAcceptance
JointJournal.history(delivery_id) -> tuple[JointCheckpoint, ...]
```

### 3. Contracts

- A one-repository plan may use `integration_checks=()`. The native delivery already requires the
  complete approved criteria, QA PASS and Reviewer APPROVE for one exact candidate.
- Parent DONE requires an immutable proof bound to the only scope unit, exact child checkpoint,
  candidate revision, ProductSpec digest and complete ordered acceptance-ID set.
- Production acceptance reconciles the native checkpoint and reads its sealed terminal artifact
  chain or candidate-verification plan/completion. A parent `DONE` label alone is never evidence.
- A retained `PLANNING + plan=null` checkpoint may recover its last approved plan from the same
  append-only parent history only to rebuild the read-only native runtime. It does not call Planner,
  reset attempts, replace the child or rewrite the journal.
- Two or more repositories still require non-empty joint checks covering every acceptance ID,
  modified unit and cross-repository interface. They reach DONE only after those commands pass on
  the complete pinned candidate set.

### 4. Validation & Error Matrix

| State | Required result |
|---|---|
| one repository, exact native DONE + accepted evidence | append single proof and parent DONE |
| one repository, retained failed integration history | preserve failure/attempts; verify native evidence and finish |
| one repository, missing or stale candidate/evidence | fail closed; no parent mutation |
| multiple repositories, empty integration checks | reject plan |
| multiple repositories, incomplete coverage or failed command | BLOCKED; retain candidates and evidence |
| repeated resume after parent DONE | no execution; completed journal is immutable |

### 5. Good / Base / Bad Cases

- Good: the only native child has exact QA/Review evidence; Manager appends the bound proof and
  completes the parent without invoking another Agent.
- Base: a historical single-repository checkpoint is waiting in integration recovery; Manager
  reconstructs its approved validation context and preserves all old attempt/failure records.
- Bad: treat child `DONE` as sufficient without reading native evidence, fabricate a successful
  integration command, or allow the single-repository shortcut for a multi-repository scope.

### 6. Tests Required

`tests/manager/test_single_repository_acceptance.py` covers legacy recovery without Agent calls,
candidate-proof drift and the unchanged multi-repository check requirement. Production-backend,
schema and browser tests cover native terminal evidence, generated schema parity and final-delivery
stage presentation.
