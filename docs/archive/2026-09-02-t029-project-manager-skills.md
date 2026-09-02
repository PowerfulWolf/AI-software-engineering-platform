# T029 Project Manager Agent Skills

## 阶段目标

把原先需要人工拼装的 ProjectWorkspaceRegistry、ProjectProfile、RuntimeWorkspaceBinder 和
Spec 编译步骤收口为 Project Manager Agent 的 typed/policy-bound Skill。调用方只提供一个
绝对项目目录，平台即能完成不污染目标项目的 prepare，或在规范冲突时明确等待人工。

## 已完成

- 新增 `ai_software_engineer.project_manager` package，公开 `ProjectManagerSkill` Protocol：
  `prepare_project`、`require_product_context`、`advance_stage`；
- `prepare_project` 有序组合 sidecar 注册/重开、ProjectProfile 发现、organization binding、
  task-free project baseline compilation 与 append-once checkpoint；
- 新增 `ProjectSpecBaseline`、project-scoped `ProjectSpecConflict`、
  `ProjectWaitingHumanRoute`、`ProjectBaselineCompilation` 及
  `schemas/project-baseline.schema.json`；
- 新增 Agent-visible `schemas/agent-skill-project-manager.schema.json`，覆盖 prepare request/result 和
  stage advance request/authorization；
- project baseline 只接受 platform/project rules，要求 hard safety，拒绝 TASK rule，且
  structured PROJECT rule 必须绑定 exact ProjectProfile source URI/hash；
- 项目规范与组织规范在 overlap scope 下值冲突时，产生 durable
  `WAITING_HUMAN`，明确 `product_agent_start_allowed=false`，不静默覆盖；
- `require_product_context` 不信任过期 result：它通过同一 service 重新 prepare/reopen
  sidecar，验证 current profile/binding/baseline 与 exact checkpoint 后才返回
  ProjectPreparation；
- `advance_stage` 要求目标阶段的 exact immutable prefix，产生绑定输入 digest 的
  authorization receipt，不编辑 stage artifact、verdict 或 Task status；
- baseline compilation 与 ProjectPreparation store 都使用 canonical envelope、temporary file、
  fsync 和 exclusive hard-link publish；并发 writer 不能覆盖首写，exact success/conflict replay
  返回第一次 durable record。

## 关键不变量

1. Project Manager Agent 只调用 typed Skill；organization identity、registry、rules、clock、
   binder 和 stores 是 runtime authority，不放进 prompt/request。
2. Project preparation 发生在需求之前，不能构造假 Task 来复用 Task SpecCompiler。
3. 原生规范在没有明确 adapter 时只是 opaque URI/hash，不把自由文本猜成规则。
4. 规范冲突必须由人类处理；没有 current PREPARED checkpoint 不启动 Product Agent。
5. 所有 AI 运行事实留在外置 sidecar/organization workspace，target project 文件字节不变。

## 验证

- T029 targeted suite：**71 passed**；
- 覆盖 Python、Java、C++ 只目录 prepare，并断言目标项目零污染；
- 覆盖 hard safety/TASK rule/source provenance、overlap conflict、WAITING_HUMAN 与
  success/conflict first-record replay；
- 覆盖 profile drift、binding/root overlap、record tamper、symlink/path boundary、exclusive
  hard-link 并发发布与 Product gate current-fact revalidation；
- 全量 pytest：**451 passed**；Ruff check/format 通过；strict Mypy：**156 source files**；
  offline sdist/wheel build 与 `git diff --check` 通过。

## 当前边界与下一阶段

T029 交付的是可被 application composition 调用的 Python Skill seam，还不是面向用户的
统一 CLI。T030 在 PREPARED checkpoint 之后接入 Product Agent 与用户确认循环；T031 接入
Designer/Planner 和调度 Skills；T032 再把“项目目录 + 需求”组合为统一、可 resume 的
CLI/E2E 入口。

本记录随 T029 集成提交归档；精确提交可通过
`git log -- docs/archive/2026-09-02-t029-project-manager-skills.md` 查询。
