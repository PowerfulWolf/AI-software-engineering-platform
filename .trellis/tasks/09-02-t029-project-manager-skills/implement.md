# T029 Implementation

## 已实现

- [x] 新增 `ProjectManagerSkill` typed facade：`prepare_project`、
  `require_product_context`、`advance_stage`；
- [x] 只接受绝对项目目录，有序组合 registry、ProjectProfile、RuntimeWorkspaceBinder、
  project baseline compiler 和 append-once stores；
- [x] 新增 task-free project baseline models/compiler，要求 hard safety、拒绝 TASK rule、保留
  opaque native sources 并校验 structured PROJECT rule provenance；
- [x] 新增 project-scoped conflict + `WAITING_HUMAN` route，Product Agent 在冲突下不可启动；
- [x] 新增 `ProjectPreparation` 和 baseline compilation 的 sidecar append-once store，使用
  exclusive hard-link publish 保护并发首写；
- [x] exact success/conflict replay 返回第一次 durable record，profile/binding/baseline drift 与
  corruption 均 fail closed；
- [x] Product context gate 每次重新 prepare/reopen current facts，不信任旧 result；
- [x] stage advance 只对 exact immutable prefix 生成 digest-bound authorization，不修改 artifact/
  verdict/status；
- [x] 新增 `schemas/project-baseline.schema.json` 与
  `schemas/agent-skill-project-manager.schema.json`；
- [x] 更新 README、contracts、milestones、Trellis code-spec 和 archive。

## 实现路径

- `src/ai_software_engineer/project_manager/baseline.py`
- `src/ai_software_engineer/project_manager/preparation.py`
- `src/ai_software_engineer/project_manager/stages.py`
- `src/ai_software_engineer/project_manager/store.py`
- `schemas/project-baseline.schema.json`
- `schemas/agent-skill-project-manager.schema.json`
- `tests/project_manager/`

## 验证

- [x] T029 targeted tests：71 passed；
- [x] Python/Java/C++ fixture 只给绝对目录即得到有效 ProjectPreparation；
- [x] 目标项目文件字节在 prepare 前后不变；
- [x] 规范冲突形成 durable WAITING_HUMAN，Product gate fail closed；
- [x] exact replay、profile drift、binding/root overlap、record tamper、symlink/path、并发首写已覆盖；
- [x] 全量 pytest：451 passed；Ruff check/format、strict Mypy（156 source files）、offline
  sdist/wheel build、`git diff --check` 全部通过。

## 未纳入

- Product Agent 对话/确认循环（T030）；
- Designer/Planner producer 与 preview/commit-dispatch（T031）；
- 统一“项目目录 + 需求”CLI/application flow 和 resume E2E（T032）；
- task DAG、向量库、分布式队列、自动 merge。
