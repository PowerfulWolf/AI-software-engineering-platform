# T032 Design：统一项目接单与可恢复交付

## 产品边界

用户只提供绝对项目目录与需求。CLI 只处理输入/输出；所有阶段由同一个
Project Manager Agent Skill facade 驱动。Product Spec 确认是唯一正常业务门禁；规范冲突、
权限拒绝、资源不足、完整性错误仍必须 fail closed 到人工处理。

v0.1 不自动 merge/deploy，不启动 daemon，不引入 DAG、消息队列或向量库。

## 应用接口

```python
class UnifiedProjectEntry(Protocol):
    def start(self, command: StartProjectDelivery) -> ProjectDeliveryResult: ...
    def reply(self, command: ReplyToProduct) -> ProjectDeliveryResult: ...
    def approve(self, command: ApproveProductSpec) -> ProjectDeliveryResult: ...
    def resume(self, command: ResumeProjectDelivery) -> ProjectDeliveryResult: ...
```

CLI 映射为：

```text
ase project start PROJECT_ROOT --requirement TEXT
ase project reply DELIVERY_ID --message TEXT
ase project approve DELIVERY_ID --checkpoint SHA256
ase project resume DELIVERY_ID
ase project status DELIVERY_ID
```

`start` 在产品需求需要澄清或确认时停止。`reply` 追加人类消息并再运行一次 Product。
`approve` 必须绑定 exact 当前 checkpoint/ProductSpec，然后自动继续 Designer、Planner、
dispatch 和 delivery。`resume` 不接受新业务事实，只从首个未完成阶段继续。

CLI 通过 `project_entry()` 解析 application host 已绑定的组织团队。宿主在进程启动时一次性调用
`configure_project_entry(...)` 注入 platform root、Agent adapters、policy 与 stores；这些是部署配置，
不是每次需求的参数。未绑定时 CLI fail closed，不能静默使用 fake Agent。

## 状态与 checkpoint

```text
PREPARING
  → PRODUCT_DISCOVERY
  → WAITING_PRODUCT_REPLY | WAITING_PRODUCT_APPROVAL
  → DESIGNING
  → PLANNING
  → DISPATCHING
  → DELIVERING
  → DONE

Any stage → WAITING_HUMAN | BLOCKED | FAILED
```

首次接单先在 checkpoint chain 外 exact-create `ProjectDeliveryIntake`，保存 canonical project root、
project/delivery identity、title、requirement 与原始 submitted_at。这样即使进程在 intake 写入后、首个
checkpoint 前，或在 Product 原生事实生成前中断，重复 start/resume 仍使用完全相同的业务命令。

append-only `ProjectDeliveryCheckpoint` 不复制子系统 payload，只保存精确身份和摘要：

```text
delivery_id / sequence / previous_checkpoint_sha256
project_id / canonical project_root / preparation_sha256
request_id / request_revision / product_checkpoint_sha256
product_spec_id+sha256 / approval_id+sha256
technical_design_id+sha256 / execution_plan_id+sha256
planning_preview_id+sha256 / dispatch_commit_id+sha256
task_id / task_revision / task_status / candidate_revision
stage_attempts / next_action / failure_code
```

每次命令先读最新 checkpoint，再从 prepare/Product/Design/Plan/Dispatch/Task 原生 store
读回事实并核对摘要。任何 identity、lineage、current revision 或 digest 漂移都不得自动
覆盖。

## 外置工作区组装

平台根目录下自动组装三个互不重叠的 sibling roots，不要求用户手工拼 Runtime paths：

```text
platform-root/
  organization/       # organization knowledge + AgentProfile
  projects/           # ProjectWorkspace registry + project sidecars
  worktrees/          # role/attempt Git worktrees
```

Runtime 的 SQLite、artifact、context、evaluation、evidence 位置全部从已绑定的 ProjectWorkspace
派生。目标项目只作为 Git source-of-truth 和 project context root，不写入 `.ase`、Agent 记忆、
checkpoint 或平台数据。

## 恢复算法

```text
start(project_root, requirement)
  prepare exact-create-or-reopen
  → Product discovery one bounded turn
  → WAITING_PRODUCT_REPLY | WAITING_PRODUCT_APPROVAL

approve(delivery_id, expected_checkpoint)
  verify exact current ProductSpec + trusted human decision
  → Designer journal/checkpoint
  → Planner plan/revision
  → read-only planning preview
  → Project Manager current-fact dispatch commit
  → TaskRepository exact-create-or-compare
  → role-isolated serial delivery

resume(delivery_id)
  verify manifest/checkpoint chain
  → reconcile every referenced native fact
  → create-or-compare missing Task from DispatchCommitRecord intent
  → reopen-or-validate role worktrees
  → continue from first incomplete native checkpoint
```

Dispatch store 与 SQLite TaskRepository 不共享事务。因此 `DispatchCommitRecord` 是 durable intent
receipt：首次写 Task；重放时读回并 exact compare；同 ID 不同 payload 立即停止。

T031 `ExecutionPlan` 是组织级抽象计划。现有 Delivery `PlanArtifact` 仅做 deterministic
Task-level materialization，继承 exact requirement/acceptance/design lineage，不再次进行需求或资源规划。

## Git/worktree 交付契约

- Coder 在 manager-owned branch worktree 从 Task `base_ref` 开始；
- Coder 提交后候选 commit 成为唯一 candidate SHA；
- QA 和 Reviewer 分别在该 candidate SHA 的 detached worktree 运行；
- 恢复只能 reopen exact task/role/attempt path、同 git common-dir、预期 branch/detached 和 revision；
- dirty worktree 是需要保留的 evidence，不得删除、reset 或覆盖；
- 主 checkout 全程必须 `git status --porcelain` 为空，不做 merge/deploy。

## 失败与路由

| 条件 | 稳定结果 | 自动重试 |
| --- | --- | --- |
| Product 需要信息 | `WAITING_PRODUCT_REPLY` | 否 |
| ProductSpec 等待确认 | `WAITING_PRODUCT_APPROVAL` | 否 |
| 规范冲突/权限/资源不可行 | `WAITING_HUMAN` | 否 |
| provider timeout/临时错误 | typed `BLOCKED` checkpoint | 上游 v0.1 不自动重试 |
| Agent invalid output | typed `BLOCKED` checkpoint | 上游 v0.1 不自动重试 |
| QA/Reviewer finding | Delivery Task 原生 retry route | 不超过 Task budget |
| checkpoint/store/worktree drift | `WAITING_HUMAN` | 否 |
| 平台不变量被破坏 | `FAILED` | 否 |

失败 checkpoint 必须记录 typed `failure_code`、安全摘要、`next_action` 和已完成的最后可验证
阶段；不保存 secret 或裸 provider payload。

`ProjectDeliveryBackend` 必须把预期的 provider/policy/output 失败转换成
`DeliveryBackendFailure(code, safe_summary)`；facade 将其写为稳定 BLOCKED checkpoint。未分类异常按进程
中断处理，保留当前 checkpoint 供 resume，不把任意异常文本写入组织事实。

上游 stage attempt 先作为审计字段保留；v0.1 只有现有 Delivery Task runtime 执行有界自动 retry。
未来若给 Product/Designer/Planner 增加自动 retry，必须先定义新的 operation/run identity、退避策略和
provider side-effect replay contract，不能简单地在 facade 中 catch 后循环。

## 测试矩阵

- Good：Python、Java、C++ 临时 Git fixture 从目录+需求到 DONE；
- Base：Product reply/approve、重复 start/approve/resume、进程重启、Task create-or-compare、同 candidate
  QA/Reviewer、主 checkout 零污染；
- Bad：non-absolute/non-Git 路径、approval stale、checkpoint tamper、prepare/spec conflict、dispatch
  drift、Task collision、worktree identity/revision drift、Agent invalid output、retry budget exhausted；
- 每条错误都验证稳定 typed 状态、无 traceback/secret 泄漏、无 partial overwrite。
