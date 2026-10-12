# 2026-10-12 生产维护与原 K1 恢复观察

## 已完成维护

原服务 PID 4722，全局 operation-summaries `active_complete=true, active=[]`。
使用有效 ASE_CONFIG 经 service stop 完成安全记录保存、执行器/索引结束与退出，无 kill。
主维护 main fast-forward 到 `9cccb5b5a0eff3b1c3dff6fc0cc5c5210b9fa550`、`uv sync --locked`
成功、origin/main 推送成功。目标 checkout（ai-workspace 下同名仓库）原 clean，fetch/ff-only
同步到同 commit。受控 service start 成功，新 PID 43582，status 可接收新操作。

独立性能回归最终为 71 passed。部署后的单次完整 Project GET 为 12.84 s / 2802572 bytes，
对比旧版本单次 15.58 s 只能证明当前仍慢，不能作为稳定提升比例或无内存泄漏证明。
2 Requests、25 Tasks；aggregate document/history payload：Request 文档 231473 bytes/7项，
Task 文档 1513328/125项，timeline 68620/36项，execution_history 873359/518项。
后续 summary/detail 优化须保留完整历史与精确授权，详见独立性能任务 research.md。

## 原需求受控恢复

父 Requirement `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`；native child
`delivery_dc5cf0aee44e5ffe0cb600557204e0d0`。无新同名 Requirement。

通过公开 POST /api/v1/operations 提交 ContinueDeliveryIntent：

- proposal Operation `operation_e481c73f2775366f6fe29257ef8e79df`，SUCCEEDED。
- 原父 checkpoint `f1fe8e58f7d73f17b9dbd9fa35450000fb710f43c85450b3a19c2097467d69aa`。
- 精确方案 `45588301d1b35b02f44762650b6195e4d4a4902b15b128e5f90bc418b4661367`。
- 方案从 trusted open_recovery_plan 完整读取并通过 integrity；capacity source 无失败 Run，
  input_mode=coder_reapply，target=9cccb5b；有完整 target_authorization，权限不允许 merge。
- 完整旧补丁再次核验 604438 bytes，SHA
  `c085ce5563e49e446c861eb4771cc3634af2f8ad0ebb27181175d9cbf80211f5`；未截断或手工适配。
- 当前页面审批明确解释未调用、旧补丁、目标基线、继续同一需求、独立 QA/Review。
- 依用户已有代理审批授权提交 exact approved_plan_sha256，操作
  `operation_4e6715d6917b2d10050d5203c6f24996` 已 RUNNING。

初次记录时尚未观察到新模型调用。后续观察如下；准备/审批/Operation 运行不等于实际交付完成。
旧 terminal Task 与事件不改写，没有直接 SQL 修改、历史清理、业务补丁手工修冲突或自动 merge。

## 真实恢复准备与模型进展（截至 03:22 UTC）

保存的里程碑：AUTHORIZATION_RECORDED 02:37:43.117824Z；TASK_SEALED
02:42:39.728281Z；DISPATCH_COMMITTED 03:03:57.383176Z；SEED_VERIFIED
03:09:01.052539Z；EXECUTION_CLAIMED 03:09:06.000010Z。
内部执行 Task 为 `task_recovery_45588301d1b35b02f44762650b6195e4`，不是新 Requirement。
Task 封存到 dispatch 实测 21 分 17.65 秒，dispatch 到 seed 核验 5 分 03.67 秒；
只读诊断发现完整历史在多层授权/fence 中重复解码。静态至少 48 轮 source 观察是
代码遍历计数，不是磁盘 I/O 实测，后续性能任务须保留所有 fresh fences。

公开 model-calls 已记录：两次 Coder `knowledge_intent` 用 native `gpt-6.1-sol`
成功（111171 ms、78499 ms）。第一次 `knowledge_assessment` 的 native CLI exit 1、
Responses sol HTTP 504、Responses astra HTTP 504 均失败；第二次 native exit 1、sol
HTTP 504 后，Responses `codex/gpt-6-astra` 在 03:15:58.196486Z 开始、60194 ms
后 HTTP 200 / SUCCEEDED。调用结束事实与实际开发/QA/Review 不混同；截至此次读取
尚未看到主 Coder 实现或 QA/Review 调用，Operation 仍 RUNNING。不能把提供方 504
或隐藏本地诊断直接定性成 ASE 平台缺陷，也不因备用模型成功宣称需求已交付。

03:25:31.203772Z 公开完整 Team 读：Task 仍 IMPLEMENTING，attempt 1 CLOSED，attempt 2
RUNNING，heartbeat 03:25:14.569670Z/lease 03:26:14.569670Z，execution_phase=ROLE_EXECUTION。
该语义是平台进入主角色准入，不等于主模型已经开始；后续读取仍只有上述8条
已完成知识调用路由记录。成功评估产物 `consultations-9a38df6bf12f1a054e2c65297e012daac44a725d000d44651d2b27891ad53724`
为 GAP / MISSING / REPOSITORY：要求 Coder 只读检查冻结源码补齐实现依据，不是向用户
追加产品问题，也未触发需求范围审批。公开页面显示 Coder RUNNING，须结合真实调用事实解读。

native exit1 的独立只读核对：现存 exact ConsoleModelCall、typed invocation outcome 和
6条执行回执仅保留退出分类、stdout/stderr SHA及HTTP结果，没有可还原的可信脱敏主错误。
部署 structured client 在代理模式分类后统一隐藏细节，临时目录已退出。因此不能确定是
额度、认证、网络或Schema问题；旧记录不能补造诊断。本轮未重复模型或读取原始prompt/key。

## 主 Coder 进行中的事实校正

独立 typed 核对得到 attempt 2 的 `DeliveryInvocationStart`：03:17:01.994116Z，
run `run_e197336456dc4dd683e2245194ad6fcc`，timeout=1800s，source仍为9cccb5b。
本机服务的真实 Codex 子进程56937在03:17:07Z启动；截至03:39读取仍在，未读取argv或secret。
相应恢复worktree中已出现learning collection模型、Schema、文档与增量测试的dirty文件。
因此主Coder确实已经开发；model-calls仅列已结束路由，8条完成知识调用不能用来推断
主模型未开始。此前parent CPU/Pydantic热点也不能归因成主调用空窗。

attempt1没有主岗位start/outcome，只有知识模型失败。当前缺少plan455...的recovery
invocation记录，代码初查为FirstCoderRunWorkspaceAdmission按attempt>1跳过；单列后续
合同排查，不能用这项待查缺口否定当前全部进度或补造已发生的准入事实。当前Operation
仍运行，主Coder outcome/完整implementation/QA/Review尚未封存，不宣称已交付。

## 本轮到时后的原 Task 自动继续

attempt2 已封存 exact `DeliveryInvocationOutcome`：FAILED / WORK_INTERRUPTED、
transient=false、无artifact。独立 `FileContinuationStore.capture_stop` 完整核验通过：
kind=local_execution_limit，stopped_at=03:47:08.182689Z，有session_proof，SHA
`f5af03c8f185e5a4ae2738bb6f902ac16af1fb8134e31a4a05ef7478522200ea`。这是真实受控
本地窗口结束，不是凭PID消失补造停止，也不是代码验收失败。

03:49:08.793839Z 公开 Team 读：attempt2 CLOSED，attempt3的
`work_b6d99b642d61ff305b09dcde1aac04050ce768cab597e94eb49afdaa7d7e86f9`
RUNNING/KNOWLEDGE_PREPARATION，Task仍IMPLEMENTING，页面明确显示本轮主执行尚未开始。
原进度由现有精确continuation路径继续，未新建Requirement或手工改业务文件。
该轮知识评估的native exit1、sol HTTP504后，astra在03:50:26.689347Z开始并于60107ms后
HTTP200成功。未触发产品范围问题或人工审批；后续实施与QA/Review仍须真实完成。
