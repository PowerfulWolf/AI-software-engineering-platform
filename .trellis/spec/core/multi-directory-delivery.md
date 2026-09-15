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
  Repository HEAD、dirty 状态、已准备事实或知识选择发生漂移，不得追加 checkpoint、Dialogue，
  也不得调用 Product Agent。成功写入 `PRODUCT_DISCOVERY` 后，`_advance` 在调用模型前再次
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
- cwd 是 check.unit_id 的候选根；环境只有 PATH、PYTHONDONTWRITEBYTECODE 和
  `ASE_UNIT_<uppercase 16hex unit suffix>`（对应候选路径）。不传 Host secrets；输出脱敏、限长、有超时。
- 每条命令后检查全部候选 HEAD/clean；仅清理未变化 worktree，保留异常现场。这是应用 guard，
  不替代 OS/container sandbox；只运行可信项目代码，测试的业务充分性仍依赖设计和独立 QA/Review。

## 4. Validation & Error Matrix

- 输入必须是存在的绝对目录；规范化别名、重复和父子选择，同一仓库合并 scope。
- 所有目录先发现/编译规范；任何规范冲突阻止 Product，交由人类处理。
- Product ID/digest 精确批准；旧 checkpoint 的 reply/approve 不得改变新事实。
- Requirement 准备后的 Repository HEAD 发生变化时，reply 必须返回
  typed `RequirementSourceRevisionDrift`，其稳定安全摘要为
  `source revision changed after Requirement preparation; create a new Requirement`；journal current
  checkpoint、Dialogue 与模型调用次数保持不变，禁止静默 rebase 或把失败回复持久化为新序列。
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
- Product 最多 20 次、Design/Plan/Integration 各 3 次调用，调用前记录尝试。模型响应到文档落盘
  的窗口可能重复计费；崩溃后的测试可能重跑，不承诺 exactly-once。
- 子仓 BLOCKED/FAILED 或联合测试非零：保留候选与证据，父需求 BLOCKED。规范/基线改变需重新
  准备新需求；不自动扩大已批准范围或引入修复 DAG。错误/漂移必须 fail closed，不能覆盖历史。
- 不自动 merge/push，不承诺跨仓库原子提交；dirty worktree 保留，不强制删除。

## 5. Good / Base / Bad Cases

- Good：后端与非相邻前端，一次批准、独立候选、读完整候选集的联合测试通过后 DONE。
- Base：一个目录使用同一 request 入口；纯文字 Product 对话保持兼容；参考目录不创建无意义 Coder Task。
- Bad：分别发起产品会话、把截图转成未校验路径塞进 prompt、先保存用户回复再检查代码基线，
  或用两个单仓 PASS 冒充接口兼容验证。

## 6. Tests Required

多目录/同仓库多模块/非相邻目录、重复和 symlink、越界写路径、reference-only、stale approval、
重新启动恢复、候选集漂移、部分成功、失败集成验收、单目录入口回归；生产桥接另用离线
structured provider + 真实 Git worktree + MySQL 验证，不消耗真实模型额度。

`test_product_reply_rejects_source_drift_before_persisting_dialogue` 与
`test_resume_rejects_source_drift_before_unblocking_requirement` 必须使用真实 JointJournal 断言：
reconcile 拒绝时 current checkpoint 仍是输入 seed；reply 的 Dialogue 未增加且 Product client
未被选择，resume 仍保持 BLOCKED。

对应 `test_directory_scope.py`、`test_joint_contracts.py`、`test_team_workspace.py`、
`test_team_host.py`、`test_requirement_attachments.py` 与 `tests/e2e/test_joint_delivery.py`。五份 joint/request canonical Schema
必须与 Pydantic 完全一致。全量 MySQL 回归不可由独立 E2E 或 skipped suite 替代。

## 7. Wrong vs Correct

Wrong：`for root in roots: native.start(root, same_requirement)`，各自产品设计后只检查子任务 DONE。

Correct：联合 Product + 人工批准 → 联合 Design/Plan → 确定性原生投影 → 各仓独立 QA/Review
→ pinned integration evidence → joint DONE。

Wrong：`client.complete(input_payload={"screenshot_path": browser_text})`。

Correct：`attachment_store.get(...) → digest/owner validation → client.complete(input_images=...)`。

Wrong：`save(user_dialogue) → reconcile() → Product`，漂移时留下伪成功的用户消息 checkpoint。

Correct：`validate command → reconcile preflight → save(user_dialogue) → reconcile fence → Product`；
任一 reconcile 失败都不能调用模型，前置失败还必须保持 journal 完全不变。

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
