> 历史快照：记录当时的交付、处置及限制，不作为当前操作指令。
> 归档于 2026-09-19，来源 docs/operator-feedback-loop.md @ c280310；正文只调整相对链接。
> 当前文档见 [分类索引](../README.md)，迁移证据见 [迁移表](document-migrations.json)。

# 平台操作与问题反馈闭环

2026-09-18 起，本项目采用用户在平台执行交付、开发协作者按具体问题排查修复的协作方式。

## 分工与交接

- 用户在 Web Console 创建需求、审批范围/计划、继续交付和验收结果。
- 开发协作者根据需求名称或 ID、触发操作和错误信息，读取对应的 Operation、Task、运行证据和规范，定位问题。
- 修复使用最小复现、fake adapter 和相关回归测试；按变更范围完成必要质量门。真实模型交付由用户在平台继续执行。
- 修复交接必须说明原因、改动、验证结果、是否需要重启、现有需求的下一步操作和回滚方式。
- 涉及持久化事实时，单列存量数据处置；保留历史，不通过改库模拟审批或重置终态 Task。
- 用户继续操作，下一处报错或流程异常进入同一反馈闭环，直到完成交付。

## 控制排查和验证成本

- 每次聚焦一个实际阻塞，按 ID 和时间定位日志、按相关章节读取规范，避免反复全仓扫描或重复收集完整上下文。
- 必要检查通过后交回操作，不为了观察交付而持续轮询、启动额外真实模型运行或重复整条交付链。
- 验证范围由变更风险与项目质量门决定；新增失败或跨层影响才扩大检查。不得为了节省 token 跳过独立 QA/Review 或伪造 verdict。
- “平台操作成功”仅表示命令处理完成；仍需查看结果中的交付阶段与阻塞原因。

## Reviewer 中断后的操作

1. 使用原有平台数据根对应的配置启动 Console；在“状态”确认 Reviewer 的主模型与备用路由。
2. 打开原需求，点击一次“继续交付”，等待该 Operation 返回。
3. 有有效候选代码时，平台可生成候选验证计划；阅读摘要后点击“批准并继续”。若旧调用已开始但没有封存完成结果，必须生成并批准新计划。
4. 当前终态候选恢复会检查是否已有同一 candidate、由终态 `qa_passed` 事件引用的 sealed QA PASS；
   有则只执行新的独立 Reviewer，没有才执行 QA → Reviewer。此路径无需重跑 Coder。只有验证发现
   实际代码缺陷时，才进入后续 Coder 修复。
5. 若再次失败，反馈需求名称/ID、点击的操作、报错文字及大致时间；截图可作为补充。停止重复点击，交由开发协作者定位该次记录。

`Candidate verification stopped before a sealed result was produced` 表示这次验证没有封存结果，
不等同于代码被 Reviewer 驳回。其“继续交付并批准新验证计划”建议符合一次调用至多执行一次的
恢复契约，但应先排除导致中断的原因，避免反复消耗审批和模型调用。2026-09-18 已修复一种原因：
新验证误用旧 Task 的模型策略，而执行器使用重启后的角色配置。新计划现在绑定当前角色策略；
设置中仅启用某个全局模型，并不表示 Reviewer 的主模型也已改为该模型。

额度恢复不等于旧调用自动恢复，也不构成通过评审的证据。运行记录中的 `UNKNOWN_EXIT`
只能证明进程失败，确认额度原因还需要相应 provider 证据。

恢复契约见 [delivery-recovery.md](../../.trellis/spec/core/delivery-recovery.md)，
常规启动与操作见 [production-setup.md](../production-setup.md)。

## 子仓库完成而需求仍显示“实现”

2026-09-18，“增加配置应用按钮”的原生交付已经完成，复用了 QA PASS，新的 Reviewer 已
APPROVE；父需求仍在 `DELIVERING`，Coder 当前没有执行。父需求阶段、角色队列和角色占用是
不同事实，不能因为父需求显示“实现”而重启 Coder。

本次阻塞原因是：恢复采用新的 preparation，联合 reconcile 已正确验证当前原生历史，但后续
deliver 又用父需求最初的 preparation 重建 runtime。修复让已有 child 从当前已验证 runtime
读取 status；DONE 结果进入父 checkpoint 和联合集成，不重复模型交付。

### 存量数据处置

需求 `delivery_multi_b7878e4343474b1114cb62e866776f3bda993ae4` 的父 checkpoint sequence 14
与原生 checkpoint sequence 55 均保留。原生 candidate 为
`d337b6bf6b42788876b9296896081ae92030e0f3`，verification completion 为
`5490d892d999efee95b2eb8d093e66c245908b23e3ba45a629a439abe45a1b51`。
旧 Task 的 BLOCKED 是不可变历史，已完成的候选验证不会把旧 Task 改成 DONE。无需改库、清队列
或生成新的验证审批；失败 Operation 也保留。

1. 从当前平台代码目录，沿用原配置重启 Console：

   ```sh
   ASE_CONFIG=/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json ./scripts/ase-console-service.sh restart
   ```

2. 刷新页面，打开原需求，点击一次“继续交付”。
3. 预期取回已完成子交付，再执行联合集成验收；通过后父需求进入 DONE。此候选不需要重新执行
   Coder、QA 或 Reviewer，也不需要重新批准验证计划。
4. 若联合测试产生新的报错，保留该 Operation ID 与错误交由排查；当前修复只验证了衔接，
   不代表生产候选的联合测试已经通过。

## 联合验收命令失败后的恢复

联合验收的命令无法启动、超时、零测试成功或非零退出时，平台应先封存脱敏的 integration
evidence，并把父需求显示为 `BLOCKED`。这不改变已经通过的 QA/Reviewer，也不应重新执行子仓库
Coder、QA 或 Reviewer。

用户下一次点击“继续交付”时，平台会保留旧计划和失败证据，创建一次有界的联合 Planner 重规划；
只有新计划通过命令策略和覆盖校验后，才会再次进入联合验收。不要直接修改 journal、候选提交或
旧计划，也不要连续重复点击同一个失败操作。

重规划期间父 journal 会短暂处于 `PLANNING` 且当前 `plan` 为空，同时保留已经完成的 child。
这个窗口的状态读取和 Planner 前置校验直接验证 child 原生 journal 的历史前缀，等新计划封存后
才重建 plan 绑定的原生 runtime；因此不能因为暂时没有新 plan 而返回“native projection requires
the approved joint artifact chain”。

### 最新存量处置：重规划读页面失败及验收预算耗尽

2026-09-18 再次核实原需求停在 sequence 21：`PLANNING + plan=null`，原生 child 已 DONE，
候选仍为 `d337b6bf6b42788876b9296896081ae92030e0f3`，integration 已用完三次、Planner 用了一次。
旧 Reader 用新/空 plan 重算 child identity，导致整个 `/api/v1/team` 返回 503；现在使用已提交
child 的精确 identity/root/history，不改数据库。此修复独立于 backend reconcile 的空 plan 修复。

原验收命令 `pytest tests/web_console/test_configuration_apply_integration.py` 的失败有两层：
执行器没找到 pytest，且该测试文件在已审核候选中不存在。现在执行器使用目标仓库既有 Python
环境，重规划读取候选而非旧基线，并在接受计划前校验显式 pytest 文件路径。

恢复步骤（取代上面较早阶段“不需要审批”的说明）：

1. 加载修复并刷新 Console，打开原“增加配置应用按钮”需求。仍使用原 MySQL 与平台目录。
2. 点击一次“继续交付”，平台只返回“批准一次补充联合验收”；核对候选 SHA 和摘要。
3. 点击“批准并继续”，追加审批记录并使用最多一次补充验收。旧三次证据不删除、预算不重置，
   已完成子仓库的 Coder/QA/Reviewer 不重跑；联合 Planner 在剩余预算内修正验收计划。
4. 只有真实联合测试通过才会进入 DONE。若第四次失败或新计划被拒绝，保留该 Operation 和错误
   反馈，不连续重复点击。不宣称已有生产联合 PASS。

无需 SQL 修复或手工修改 journal。本次开发验证使用脚本化模型/隔离测试库，不代替以上用户审批。
若需要回滚，先停止交付，只撤回这次 Reader/补充验收/执行环境改动，保留所有审计记录；一旦已经
批准补充验收，不要用不认识新增审批字段的旧服务继续写 journal，应先部署兼容版本。

## 更正：单仓不执行联合验收

上述“补充联合验收”步骤只适用于两个及以上仓库。对于只有一个代码仓库的需求，平台复核该仓
原生交付中已经封存的完整验收项、QA PASS、Reviewer APPROVE 和精确候选提交，然后追加
`SingleRepositoryAcceptance` 并完成父需求。不会再运行 Planner、Coder、QA、Reviewer，也不会
消耗或重置旧的 integration 次数。

存量单仓需求即使停在 `PLANNING + plan=null`，也只从同一父 journal 找回原批准计划用于重建
只读验证上下文；旧失败记录、候选和 child checkpoint 全部保留。重启加载新版本后，页面应显示
“等待交付确认”，交付流程定位到“交付”。用户点击一次“继续交付”即可触发证据复核；若证据
缺失或漂移，操作失败并保留原状态，不允许手工把数据库或 journal 改成 DONE。
