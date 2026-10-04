# 面向产品用户的交付中断与工程恢复重构

## 目标与用户授权

用户是产品负责人。已于 2026-10-04 明确授权按方向复盘/具体方案重构恢复流程，完成增量验证并提交推送。最新指示覆盖先前的重新交付计划：重构完成后删除现有两个 K1（包括已关闭需求），暂不新建或交付；用户以后明确要求时才恢复交付。无需再次询问已授权工程操作。

## 需求

- 失败原因、保留工作成果、处理决定分开。权限内中断草稿不一律认定 POLICY_VIOLATION。
- 普通新 Task 使用冻结的版本化工程续跑授权、精确 interruption receipt 与单次 admission。在可信执行已停止、原基线/权限/预算不变、草稿可完整核验时同 Task/branch 新 Run/new claim 接续；禁止同 Run dirty fallback。
- 可等待问题保持最近 Task checkpoint，使用现有 WorkItem wait/retry 及真实 Dispatcher，不增加第二套执行引擎。
- 业务问题交产品，工程问题由团队/工程授权者处理；自动动作记 policy 授权，不伪造人工批准。旧 Task/审批不追溯赋权。
- 产品视图准确展示阶段、执行/等待状态、处理责任与下一步；完整记录中断/自动处理/QA/Review/返工，技术身份放工程详情。
- 保留原 v0.1 串行交付、权限与 evidence、独立 QA/Review、预算/fence、不可变历史。Git inventory 不冒充 OS 级副作用隔离。
- 完成发布后，通过正式平台删除入口移除精确定位的两个 K1，产品列表/详情/交付入口一致不可继续；删除事实留审计，原 immutable 运行事实不改写。暂不创建或启动新需求。

## 验收

- [x] 合法 dirty interruption 经过真实 Git/队列 fixture 跨重启接续，同 Task/branch、新 Run/claim、预算一次记账；没有模型 progress 时不伪造它。
- [x] Receipt 重放、漂移、live process、真实违规、未知输出、HEAD 移动、终态、预算耗尽、旧 Task 无授权均安全拒绝自动接续。
- [x] 同 Run fallback 不越过 dirty admission；无草稿服务故障仍能正常重试。
- [x] Queue waiting/heartbeat/重试状态和产品页一致；无假运行、泛化“请产品批准工程问题”或八条历史截断。
- [x] 增量 Ruff/mypy/contract/unit/public-entry/Git-MySQL/DOM 测试通过，独立复核；不跑全量。
- [ ] 正式删除能审计终止旧需求遗留的已停止非终态 Task/队列；live process/有效 Lease 仍拒绝，不调用模型、不手工改库。
- [ ] 提交推送、空闲部署，两个 K1 正式删除且产品界面/继续入口一致；其他需求不受影响，原审计事实不改写，没有新 K1 或模型调用。

## 允许路径与约束

实现允许 src/ai_software_engineer/{agents,domain,git,orchestration,work_queue,manager,recovery,web_console,team_view}/、runtime.py、role_workspace.py、production 配置模块、对应 tests/、schemas/、scripts/ 的 schema 同步脚本和相关 docs/.trellis/spec/。工程根 agent 可写规范；业务 Coder 不得写 .trellis。不得提交原有 .ase/、凭据、运行 sidecar 或数据库。

每个 worker 持有明确文件责任，适配其他 worker 改动，不回退他人工作。第一实现切片限定可证明停机、无候选/accepted output、普通文本新增/修改的 Coder 中断；能力不足或超范围准确交工程处理，后续按测试覆盖扩展，不能假装万能恢复。

## 验证与回滚

增量 pytest 选择 receipt/policy/Codex/fallback/retry/queue/native-entry/Console，Node DOM，变更文件 Ruff/mypy，Schema 正反和旧 digest。仅使用已配置隔离测试 MySQL。存量处置走正式 API；不用生产 SQL 改状态、不清理脏现场。

发布前平台服务与目标 clone 保持当前 3162402，服务空闲才重启；目标需求 source 与平台 runtime 版本分别对待。空闲 revert 修复提交并重启，保存新增 receipt/policy 兼容读取及旧 K1 历史；不能借回滚执行错误旧计划。

## 设计依据

docs/architecture/2026-10-04-product-oriented-delivery-proposal.md，AGENTS.md，.trellis/spec/core/persistent-work-queue.md、execution-retry-policy.md、delivery-recovery.md、live-team-view.md。已确认采用现有 queue + typed facts/admission 方案，不再做产品偏好询问。
