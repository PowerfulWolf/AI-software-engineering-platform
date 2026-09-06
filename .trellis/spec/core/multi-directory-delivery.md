# 多目录联合交付契约

## 1. Scope / Trigger

适用于 `multi_directory/`、Host/CLI、批准投影、候选集合及恢复。入口接受 1–32 个非相邻目录，不要求项目组、
manifest 或共同父目录。一个 Git 仓库只形成一个 execution unit；保留用户所选模块目录的
写入上界。联合事实保存在 `<platform_root>/companies/<company_id>/requests/<delivery_multi_id>/`，
各仓库事实放在同公司 `projects/<project-id>/`。Agent 仍归组织，代码不复制、不污染。

## 2. Signatures

```text
ase request create ABSOLUTE_DIR... --name NAME
ase request discuss DELIVERY_ID --checkpoint SHA256 --message TEXT
ase request approve DELIVERY_ID --checkpoint SHA256 [--approval-reference REF]
ase request status DELIVERY_ID
ase request resume DELIVERY_ID
```

`OrganizationTeamHost.requirement_entry() -> JointDeliveryService` 装配生产后端。
`create(CreateRequirementProject) / reply(ReplyToProduct) / approve(ApproveProductSpec)
/ resume(ResumeProjectDelivery) / status(str)` 均返回 `JointDeliveryResult(checkpoint=...)`。
旧 `ase project start DIR... --requirement TEXT` 兼容：单根目录走原生、多目录走联合服务；
单仓模块目录应使用 `request create`，由 scope discovery 归并为真实仓库根。

## 3. Contracts

`DirectoryScope → 全部 PrepareProjectResult → JointProductSpec → exact human approval
→ JointTechnicalDesign → JointExecutionPlan → per-repository delivery → integration evidence`。
多目录不是多个互不相关的 Product 会话。子仓库 Product/Design/Plan 是已批准联合事实的确定性
投影，不重新询问用户、不重新生成需求。每个子 Task 仍串行 Coder → QA → Reviewer。

- create 准备所有目录后停在 READY_FOR_DISCUSSION，不调用模型。同名+同公司+同 scope（含
  base SHA）幂等恢复；新需求使用新名称。dialogue、product_spec、approval、design、plan、children、
  integration、attempts 和 next_action 都保存在带 sequence/前后 SHA 的 JointCheckpoint。
- 主状态链：PREPARING → READY_FOR_DISCUSSION → PRODUCT_DISCOVERY → WAITING_PRODUCT_APPROVAL
  → DESIGNING → PLANNING → DELIVERING → INTEGRATING → DONE；另有 WAITING_PRODUCT_REPLY、
  WAITING_HUMAN 和 BLOCKED。Task 的原生状态机不变。
- DerivedStageInputs 从已批准联合文档选取全局 requirement 子集，映射为原生局部 req/ac IDs；
  `joint-approval:<parent-id>:<approval-digest>:<unit-id>` 只验证精确父批准，不是 Agent 自批。
- 子仓 `joint.approved_context` 包含联合方案、接口、验收及已完成声明依赖的候选事实；原生
  dispatch、Task、worktree、独立 QA/Review 和 Artifact/Evidence 守卫不得绕过。
- integration 使用全部 write candidate SHA 和 reference-only base SHA，在外置 detached worktrees
  执行。每条接口至少一个 check 同时消费 producer 和全部 consumers；证据绑定精确 plan/candidate set。
- 测试 argv 必须同时匹配 ProjectProfile allowlist 和支持的测试前缀，禁止 shell/inline code、
  install/deploy、inspection 替代测试、常见 help/collect-only/skip-tests 参数；明确零测试的成功退出拒绝。
- cwd 是 check.unit_id 的候选根；环境只有 PATH、PYTHONDONTWRITEBYTECODE 和
  `ASE_UNIT_<uppercase 16hex unit suffix>`（对应候选路径）。不传 Host secrets；输出脱敏、限长、有超时。
- 每条命令后检查全部候选 HEAD/clean；仅清理未变化 worktree，保留异常现场。这是应用 guard，
  不替代 OS/container sandbox；只运行可信项目代码，测试的业务充分性仍依赖设计和独立 QA/Review。

## 4. Validation & Error Matrix

- 输入必须是存在的绝对目录；规范化别名、重复和父子选择，同一仓库合并 scope。
- 所有目录先发现/编译规范；任何规范冲突阻止 Product，交由人类处理。
- Product ID/digest 精确批准；旧 checkpoint 的 reply/approve 不得改变新事实。
- Design 必须划分全部 unit 为 write 或 reference-only；覆盖全部产品 requirement IDs；
  component paths 不得扩大 selected scopes。接口的 producer/consumer 必须属于本次输入。
- Planner 只给有界串行顺序，不引入通用 DAG；依赖不得指向尚未完成的 write unit。
- 各仓库候选、QA/Review、子 checkpoint 必须与联合 spec/design/plan 绑定；partial DONE
  不等于联合 DONE。集成验收引用完整 candidate set，在外置 detached worktrees 执行受控命令。
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
- Base：一个目录使用同一 request 入口；参考目录不创建无意义 Coder Task。
- Bad：分别发起产品会话，或用两个单仓 PASS 冒充接口兼容验证。

## 6. Tests Required

多目录/同仓库多模块/非相邻目录、重复和 symlink、越界写路径、reference-only、stale approval、
重新启动恢复、候选集漂移、部分成功、失败集成验收、单目录入口回归；生产桥接另用离线
structured provider + 真实 Git worktree + MySQL 验证，不消耗真实模型额度。

对应 `test_directory_scope.py`、`test_joint_contracts.py`、`test_company_workspace.py`、
`test_company_host.py` 与 `tests/e2e/test_joint_delivery.py`。五份 joint/request canonical Schema
必须与 Pydantic 完全一致。全量 MySQL 回归不可由独立 E2E 或 skipped suite 替代。

## 7. Wrong vs Correct

Wrong：`for root in roots: native.start(root, same_requirement)`，各自产品设计后只检查子任务 DONE。

Correct：联合 Product + 人工批准 → 联合 Design/Plan → 确定性原生投影 → 各仓独立 QA/Review
→ pinned integration evidence → joint DONE。

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

Regression: `tests/project_manager/test_joint_planner_feedback.py` exercises service + real journal
with deterministic models, restart, exact input IDs, preserved approval, strict rejection, and
attempt exhaustion. It does not claim live model success or independent QA/Review of feature code.

## 9. Exact integration command context (T039)

Scope: Planner context and `ProductionJointBackend.validate_plan` command preflight. General
ProjectProfile commands are broader than integration tests; neither list alone grants execution.
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
