# T030 Implementation

## 已实现

- [x] 新增组织级 `OrganizationRole`，与只服务 Delivery runtime 的 `AgentRole` 明确分离；
- [x] 新增 Task-free Product context，携带并校验完整 `ProjectProfile`、`ProjectSpecBaseline`、
  preparation、request、对话前缀和 current ProductSpec；
- [x] 新增 Product adapter/fake adapter，覆盖 clarification、ready、timeout、provider error 和
  invalid output，Product permissions 禁止 code/shell/state/approval；
- [x] 新增 immutable dialogue、request revision、ProductSpec/Approval、operation、checkpoint records；
- [x] 新增 Product discovery service：start、human message、run、request changes、human approval；
- [x] 用户决定只接受 trusted verifier reference；Product Agent 不能构造 decision/operator/rationale；
- [x] exact ProductSpec approval 通过 Project Manager current-fact guard 后才解锁 Designer；返回的
  stage authorization 还会校验 target、project 和完整 input digest prefix；
- [x] operation receipt 是外部结果校验后的第一个 durable write，携带完整 effect bundle、checkpoint、
  verified decision 和 authorization；中断重放不再次调用 adapter/verifier/advancer；
- [x] Product file store 的写和读均使用 root-relative dirfd、`O_NOFOLLOW`、inode/regular-file 校验，
  覆盖 symlink/path swap、并发首写与篡改；
- [x] 新增四个 Product JSON Schema，更新 README、contracts、milestones、Trellis spec 和 archive。

## 实现路径

- `src/ai_software_engineer/product/`
- `src/ai_software_engineer/domain/enums.py`
- `src/ai_software_engineer/domain/workforce.py`
- `schemas/product-*.schema.json`
- `tests/product/`

## 验证

- [x] Product targeted tests：51 passed；
- [x] 受影响 Product/ProjectManager/Agent/Context/Workforce/Projection/Scheduling/RuntimeWorkspace：
  232 passed；
- [x] 全量 pytest：504 passed；
- [x] Ruff check/format、strict Mypy（169 source files）、offline sdist/wheel build、
  `git diff --check` 全部通过。

## 未纳入

- Designer/Planner producer、read-only preview 与 Project Manager commit-dispatch（T031）；
- 统一“项目目录 + 需求”入口、durable resume 和跨语言 E2E（T032）；
- Reporter（T033，按约定暂停）；
- 单 Task DAG、向量库、分布式队列、自动 merge/deploy。
