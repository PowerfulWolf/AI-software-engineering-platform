# T028 Design

## Boundary

Project Manager 是组织级团队领导 Agent。项目准备、阶段路由、状态校验、提交分配和交付被实现为
它的 typed、policy-bound Skills；这些 Skills 内部调用 deterministic application services 与 stores。
Agent 可以解释、澄清和提出建议，但不直接持有 store、Scheduler、ModelRouter 或其他 Agent 的
启动权限。

Project Manager Agent 先调用 `prepare_project` Skill：注册外置 sidecar、发现 `ProjectProfile`、
校验 organization binding，并编译 platform + project baseline rules。Task constraints 尚不存在，
因此在 Delivery Task 派生后必须再次编译 task-scoped rules；Prepare 不能声称提前解决未知需求冲突。

原始需求先进入独立 `ProjectRequest` 生命周期，而不是直接创建现有 `Task`。Product Agent 负责
把需求对话收敛为 `ProductSpec`；Solution Designer Agent 将冻结版本转换为 `TechnicalDesign`；
Planner Agent 再生成 `ExecutionPlan`，声明阶段、能力、风险、检查点和 BrainTier 需求。Planner 可
调用 read-only `preview_schedule`/`preview_model_route` Skills 验证计划可行性，但不能提交 concrete
Agent/provider/model。Project Manager Agent 接受计划后调用 `commit_dispatch` Skill，由同一
Scheduler/ModelRouter engines 复核并持久化 typed Assignment/Lease/ModelSelection。只有这些上游
事实满足冻结/审批规则后，才确定性派生一个现有 Delivery Task 并启动串行 Orchestrator。

推荐采用“一个用户入口、内部多阶段 checkpoint”的深模块接口。CLI/未来 UI 都调用同一个
Project Manager Agent Skill facade；用户看到连续需求对话，内部依次持久化 ProjectPreparation、
ProjectRequest、ProductSpec、TechnicalDesign、ExecutionPlan 和 Delivery Task。Scheduler/ModelRouter
保持纯、确定和可重放。

Skill 只是 Agent 的受控能力入口，不是把 service 逻辑复制进 prompt。Preview Skill 无写权限；
commit Skill 持有最小持久化端口并必须重新校验 preview 输入，防止 Planner 的建议被当成授权事实。

## Approval gate

Product Agent 只产出 immutable `ProductSpec(status=READY_FOR_REVIEW)`，不能自行把它标记为已批准。
用户决定使用独立 `ProductSpecApproval` 记录：它引用 exact Project、Request、spec ID 和 spec digest，
并记录 `APPROVED` 或 `REQUEST_CHANGES`、operator、rationale 和时间。设计阶段必须同时验证 spec 与
approval 的 identity/integrity；修改需求时生成新 spec version 与新 approval，旧记录不覆盖。

## T028 module seam

```text
domain/project_delivery.py
  ProjectPreparation
  ProjectRequest
  ProductSpec + ProductSpecApproval
  TechnicalDesign
  ExecutionPlan
  validate_stage_chain(...)
  derive_delivery_task(...)

schemas/
  project-preparation.schema.json
  project-request.schema.json
  product-spec.schema.json
  product-spec-approval.schema.json
  technical-design.schema.json
  execution-plan.schema.json
```

这些 stage document 是可验证、不可变的上游 artifacts，但 T028 不把它们硬塞进现有四类 Delivery
Artifact envelope。T030/T031 接入 AgentAdapter 时再统一扩展 producer/run/context lineage，避免先
破坏已经稳定的 Coder/QA/Reviewer wire contract。

## Core guards

- 所有 model `extra=forbid/frozen`，ID、aware datetime、唯一性和引用关系在边界校验；
- stage digest 来自 canonical JSON，排除观察时间与 digest 字段；
- Technical Design 必须精确覆盖 Product Spec 的 requirement/acceptance ID 集合；
- Execution Plan v0.1 只允许 `coder → qa → reviewer` 三阶段，声明 capabilities/risk/BrainTier，
  禁止 concrete Agent ID、provider、model、Assignment 或 Lease；
- `derive_delivery_task` 先重验整条 stage chain，再把 Product Spec acceptance criteria 原样投影为
  NEW Task，并把上游 artifact ID/digest 写入 metadata；
- Project Preparation baseline 与 Task-scoped compilation 是两个 checkpoint，T029 负责实现前者，
  T032 在 Task 派生后复用现有 `SpecCompiler` 实现后者。

## Failure matrix

| Failure | Result |
|---|---|
| Product Spec 未批准或 REQUEST_CHANGES | `ProductApprovalRequired`，Designer 不启动 |
| approval/spec digest 或 Request/Project 不同 | `StageContractMismatch` |
| Design coverage 缺失或多出未知 ID | `StageContractMismatch` |
| Execution Plan 引用错误 design/spec 或非串行 role | Pydantic/`StageContractMismatch` |
| 任一 digest 被篡改 | `StageIntegrityError` |
| 派生 Task 时 repository/project root 或 base ref 不可信 | typed validation，Task 不创建 |

## Good / Base / Bad

- **Good**：用户批准 exact Product Spec，Design 全覆盖，Planner 产出抽象资源需求，最终确定性派生
  一个带完整 lineage 的 NEW Task。
- **Base**：全部 contract 可用本地 fixture 离线验证，不需要模型、Git 命令、队列或数据库。
- **Bad**：Product Agent 自批需求、Designer 审错版本、Planner 写死模型/Agent，或直接从聊天文本
  创建缺验收标准的 Task。
