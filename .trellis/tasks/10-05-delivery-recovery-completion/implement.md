# 完整恢复重构实现与验收记录

实现与增量验收已完成，独立审查进入发布收口；提交、推送与空闲部署尚待执行。不能以首轮切片或单个 helper 的存在声称整体完成。

用户暂停业务交付保持有效。两个 K1 保持删除，不新建生产需求、不调用生产业务模型、不恢复原需求。只运行受影响增量。

## 完整目标与生产接线

| PRD 目标 | 实现与入口 | 增量证据 |
| --- | --- | --- |
| 多轮中断/返工保持原 Task、分支与完整草稿 | v2 per-Run receipt/admission、Native/Responses Coder、Production Factory、Supervisor、完整 UTF-8 mutation capture | public repeat/progress/QA feedback/Review feedback；真实 Git/SQLite Responses 故障和重启；完整增删改名/mode tests |
| 共用 typed 处置，等待保存阶段、释放租约 | deterministic DeliveryDisposition、WorkerDeliveryFailureControl、RoleQueue owner fence、Manager/Reader 同源 | domain disposition、MySQL wait resolution、public preflight/QA/Review preparation waits、Worker 歧义历史等待 |
| 真实调查与可操作工程处理 | durable invocation start/outcome、NOT_STARTED/FINISHED/UNCERTAIN preparation intent；Host inspect/resolve、Console 精确工程 intent | 未开始重领、封存结果重放、已拒 outcome 禁止重放、事实漂移/未知停机/重复决定拒绝 |
| 产品/工程授权分离 | trusted LocalOperatorPrincipal、Product 最早边界检查、冻结 EngineeringPolicy/额度账本、精确 spec 批准 | start/reply/approve/resume/retry Engineering-only 拒绝与零事实；budget/restart drift；DOM 精确决定 |
| 平台更新与源码基线分开 | append-only baseline binding/queue source overlay，原 Task/base/批准不改写，同分支完整旧 patch；Host/Console propose/execute | preserve_draft/coder_reapply 公开完成与 conflict；同 slot 二次 baseline/三次 preflight；历史源与 crash replay |
| Planner 有界计划、Coder 可执行窗口、验证预检 | frozen PlanExecutionWindow、trusted CoderWorkSlice、真实 registered preflight；全部 fallback exact routes 在 invocation start 前准备 | partition/budget/source drift、joint/new intake frozen window；native mixed routes、QA/Review same-SHA新父链重验 |
| 前端状态/责任/完整历史 | validated accepted receipts ∪ StateEvents；store-owned seal/claim/lineage 排序；保留 QA/Review/Coder全轮次与环境理由；工程证据折叠 | public QA inconclusive WAIT/DONE ProductionTeamReader、超过八条反复反馈、伪造/重复 provider 时间、DOM完整历史/精确按钮 |
| 正向、拒绝与重启的公开组合 | 原 TeamHost/Requirement service/Dispatcher/Worker/真实 Context 与 Artifact pipeline，独立三 Agent 对同 candidate 验收 | public continuation/baseline、精确知识解答旧回归、工程验证恢复、Schema/权限/预算/漂移、独立 check |

## 实际发现及修正

除最初七项独立审查遗漏，本轮真实接线又修复了以下问题：

- QA/Review 返工只按相同 SHA 复用旧 verdict，而没有精确实施/QA parent 与本轮 reservation；现在原报告只读输入、每次新报告 supersedes 原报告，三角色权限共用 DELIVERY_ROLE_INPUTS。
- Baseline required Context 在知识 gate 之后插入，改变 final Context ID；现在先基线后知识，外层幂等验证。未调用准备同 attempt 重领原先复用同内容 Context；现在加入真实 claim required section。
- 旧 WAIT_RESOLVED 阻止同 slot 后续合法等待决定；现在 exact digest/body 幂等，其他决定按当前等待/facts/owner fence 验证。
- 同步 Responses provider 故障后的本轮合法草稿被误分类权限违规；现在真实串行工具返回后封存 exact synchronous stop，不制造 PID，不允许同 Run fallback。
- 每轮 HTTP 重获完整 timeout、持续慢滴延长时间窗口；现在一个 monotonic deadline 覆盖 transport 状态行/header/framing/body 与命令。收到 final 后时间耗尽不得假称没有输出；普通 tool narration 不冒充 final artifact。
- 工具原子写把所有源码变成 mkstemp 的 0600，导致合法草稿无法捕获；现保留原 regular mode，新文件 0644。受控命令不能证明子进程/输出管道停止时返回独立 uncertainty，registry 不吞成普通拒绝。
- 已拒 INVALID_OUTPUT/PLATFORM_BUG outcome 被广告为 replay，反复恢复同一失败；现在 OUTCOME_REJECTED 明确工程下一步，没有无效按钮，也不退款。
- Accepted inconclusive QA 没有 StateEvent 因而消失；现读取验证过的 accepted receipts 完整保留 criteria、命令、finding、environment、evidence 和全部轮次。
- Provider created_at/随机 ID 排错历史甚至选错当前报告；现共用平台 seal、durable stream 与完整 lineage 顺序。未封存、循环或歧义拒绝为工程等待，不留已失效的“运行中”状态。
- Baseline 后失败 source 仍用原 Task.base；新输入 SHA 又被误当候选；现在按实际执行输入记录失败，仅从未被基线取代的 accepted Implementation 保留候选，终态重建也遵守同一规则。
- 已封存 QA 验收覆盖不符等平台契约异常绕过等待直接 FAILED；新授权任务现在 typed PLATFORM_BUG 等待，保留 checkpoint、source 与原产物；legacy 终态契约兼容。
- MySQL 跨连接 REPEATABLE READ 旧读快照误挡新 reservation；现 READ COMMITTED，写侧锁与 owner fence 保留。

## 验证结果

- changed 非 MySQL 增量：380 条去重用例通过（初跑379通过，新增 TaskView 测试 fixture 修正后单独复验）；未跑全量。
- Responses/HTTP/tool/Context/知识恢复相关最终组合：64 passed；后续 final+narration 六个边界场景单独全部通过。
- Schema canonical/continuation/resolution：128 passed；新同步 stop 三用例均通过。
- verification environment/Python executor/mixed routes/Product 权限：51 passed，2 个显式本地 sandbox/toolchain opt-in 场景未运行。
- 共享排序、baseline、契约等待与终态候选聚焦组合：45 passed；retry/verification lineage/native continuation：29 passed。
- MySQL wait resolution：18 passed；新增真实 Worker accepted-history refusal/lease release/reentry：1 passed。
- DOM 当前状态、完整历史、工程/基线交互：16 passed。
- 159 个受影响 Python 文件 Ruff/format/strict Mypy 全通过；git diff --check 通过。
- public Host continuation/baseline 14 条已通过（12 条原组通过，2 条因环境冲突串行复验通过）。测试 MySQL 曾因根 Agent 两组误并发清库发生环境冲突；已停并发，仅串行重跑受影响用例，不作为平台失败修复，也不隐去验证过程。
- 旧 backend lease-loss 用例期望未知调用自动 DONE，与新安全契约不符。已改为公开入口精确验证 start 一份/outcome 零、IMPLEMENTING/无候选、工程 EXECUTION_UNCERTAIN 等待、claim 释放、调查明确缺结果/停止证明且无恢复按钮、二次继续零调用。整个 backend 增量文件 17 passed，Ruff/format/strict Mypy通过；共享排序/终态/工程历史最终组合 71 passed。
- 独立 check 与交叉代理复核发现均已处理，最后源码没有 remaining must-fix。

## 存量数据处置

不直接修改生产 Task、批准、verdict、预算、原 source/base 或状态事件。新授权仅冻结于新 Task；旧 policy=None 不追补。新增 work_queue_execution_baselines 通过既有队列初始化创建，记录 append-only 消费/source overlay，旧 step 与调用 source 不被追溯修改。

两个 K1 的正式 tombstone 和审计/sidecar/dirty 现场保留。发布前 GET 已核四个 Project：44 个现有可见交付/验证记录、261 个 Operation、零执行中角色和零 pending Operation。保存精确 ID、status、phase、candidate 的只读基线，部署后比较。部分既有父需求显示 BLOCKED、另有 VERIFIED 的验收记录；以原事实保持一致，不凭摘要改成 DONE。

新非终态等待通过公开工程 inspect→精确 proof→resolve→原 Requirement Supervisor 继续。已拒结果无可用重放；缺真实停机/产物证明时显示具体工程责任与前提，不能靠过期租约、用户 bool 或 hash 单独重新执行。旧终态不复活；暂停期间不实际执行存量恢复。

## 已知边界与回滚

增量 public fixtures 使用真实 Git/MySQL/Context/claim/Artifact 链，模型和低层外部资源用受控 fake ports。它们证明恢复流程与权限契约，不证明真实业务模型、Docker/全部 OS sandbox 的部署验收；本轮遵守暂停业务交付，不以新建需求测试上线。未运行全量测试，也不宣称平台零 Bug。缺能力、超出授权/预算、源冲突或无法确认执行结束仍是明确工程/产品处理边界。

空闲发布后仅做 GET/页面验收；任务状态、候选和 Operation 必须与发布前相同。回滚前停止新增工程操作，保留新 Schema/receipt/binding/authorization 的读能力；不能删除新增表、审计或完整补丁。已经产生新记录时优先前向修复，不能退回不认识这些事实的版本。没有业务调用的新发布可空闲回退到前一提交，保留全部持久化事实，再恢复服务。
