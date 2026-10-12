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

## 第三轮主执行前的容量停止

原 Operation operation_4e6715d6917b2d10050d5203c6f24996 已 SUCCEEDED，仅表示本次操作收尾，不是需求完成。当前父 checkpoint 为 ea13981bbf62a8d9d6ad2fd94c421e5585deb740b2fa42375976a214005ed2a5。Task仍IMPLEMENTING，attempt3 WorkItem WAITING_DEPENDENCY，reason_code=CONTEXT_CAPACITY，engineering责任。

精确容量 receipt 7881f2332a7bfef9c73858d6f67c9d0fe7f742a1998ae7d85e3e58cf85afbd19：sealed Context248568，最终native输入285444 >256000，主模型未启动。对应Context ctx_f40fc856979f97e9fbd5f03011311debe76c9356041a9b6ade36f7747987da28。仍必需的完整604438byte历史reapply补丁与本轮当前工作区135493字符草稿是不同内容，不能直接按重复补丁删除。

新独立Trellis任务10-12-preserved-continuation-input仅改变已核验同工作区v2续跑的阅读输入；完整capture/stop/ownership/当前现场校验及旧reapply全文均保留。原Requirement、所有旧Task/Operation/预算和审批保持不变，后续只能走公开exact PAUSE/RESUME。全局operation-summaries已确认active_complete=true、active=[]；部署仍需最终fresh空闲检查和受控stop。

实际native `_compile_input`只读重放（包括当前manager tooling与输出Schema）：原输入精确复现285444，新阅读输入252481 <=256000。零provider调用、零生产事实写入，临时准备资源已正常关闭。纯prompt的251902不包含实际tooling，不能用于宣称最终输入大小。

## 已审查修复的受控发布与生产读取验收（04:38 UTC 之后）

再次通过全局 operation-summaries 确认 `active_complete=true, active=[]`、总数336；
旧 PID43582 经有效 ASE_CONFIG 的受控 stop 保存操作/写入、确认执行器与索引结束后退出，
没有强杀。维护 main fast-forward 到 `0c1053540beb214e0b4839a28906909c80957353`，
`uv sync --locked` 成功，origin/main 与集成分支均推送成功。受控启动新 PID37024。
K1 注册源码 checkout 原 clean，fetch/ff-only 同步到同一提交；这一步没有改变 Task 的
原批准基线或原 Coder worktree。Console 声明 team_read_contract_version=v0.1、
operation_contract_version=7、delivery_ready=true。

生产首次若干 HTTP 摘要请求返回 `503 TEAM_READ_IN_PROGRESS`，约九分钟跨度内采样数次后读取成功。
没有同一 active flight 的身份与起止记录，不能将这些样本称为同一个读取连续卡住九分钟；
旧页面的完整轮询与其他读请求竞争也尚未排除。
服务仍响应 Console/Operation 读取；不能凭此称为内部装配异常或已确认的 gate 泄漏。
独立纯读重放摘要4.463s、full14.912s均成功；macOS 拒绝 Python 进程栈采样，未提权或发信号。
首次繁忙样本的具体占用来源仍未证实，后续成功不能抹去这项观察。

恢复后串行 HTTP 验收（单次观察，不是延迟保证）：

| 读取 | 秒 | 响应 bytes | 完整内容 |
| --- | ---: | ---: | --- |
| 当前 Project summary | 3.373 | 78031 | 2 Requests / 25 Tasks 的当前事实 |
| 选中 K1 Requirement detail | 7.626 | 221156 | 3 documents / 1 dialogue |
| 选中 K1 Task detail | 14.459 | 1549614 | 19 documents / 13 timeline / 210 execution_history / 19 runs |
| 兼容 Project full | 11.366 | 2957661 | 完整原 v0.2 响应 |

所有2个 Request 和25个 Task 的当前字段与兼容 full 逐字段完全相等；选中资源的完整
正文/历史也逐字段相等。详情 locator 全量映射 expected 字段且返回 scope 精确匹配。
没有八条历史截断。未能使用已登录生产浏览器手动验收，不能将隔离 Chrome 增量测试或
这些 HTTP 比较表述成已手动验证生产点击体验。服务 RSS 的单次下降/上升也不证明没有泄漏。

## 原需求基线方案的历史知识 claim 缺口

公开 PROPOSE_EXECUTION_BASELINE Operation
`operation_0231e2ce23a7c6d9617bed6607a6204e` 被受理后 FAILED / COMMAND_REJECTED，
04:41:46.978990Z 封存原因：`历史 claim 没有可验证的调用或执行前停止记录`。
提案以原 Task revision2、原 attempt3 WorkItem、父 checkpoint ea13981...、source9cccb5b
精确绑定 target0c10535、preserve_draft；未发布可批准计划，未移动原 Coder 分支。

独立 typed store 读取确认原 attempt1 的知识 lane042bb062...、真实原 claim
`lease_3bc0dd234365efd421c9b527` / `work_8c37cb243927c144045e0da348c1a9be3302048eb274c0180047490b3b6db1e0`：
intent outcome065452a2...为RETURNED，assessment outcome9e7f319c...为FAILED/
PROVIDER_UNAVAILABLE。两者完整 hash 校验，所有 embedded executions 均与独立
knowledge-execution-records 回读相等：原生 route 有真实 stop，HTTP route 有本地 round-trip。
HTTP 返回不证明远端停止。此轮没有 main DeliveryInvocationStart；只有 attempt2 有主岗位启动。

当前 collector 只将无 main 的历史 claims 分为 capacity 或 WAIT_ENGINEERING preflight，
遗漏知识准备已封存失败这一类。新 Trellis 任务10-12-baseline-knowledge-claim-proof修复
完整知识事实与 no-main 否定扫描的结合；不能仅靠缺 start、PID 消失或空目录猜测未执行。
原失败 Operation、Task、审批、预算与完整开发进度全部保留，没有 SQL 改写或补造旧 receipt。
截至本段记录，K1仍为IMPLEMENTING/CONTEXT_CAPACITY等待，未进入QA/Review或交付完成。

## 知识 claim 修复发布后的真实重提（05:20 UTC）

独立审查及增量验证后的54ed9fe已发布：全局337条operation中active_complete=true、active=[]；
PID37024受控stop保存全部操作/写入并确认执行器和索引结束。维护main与origin/main同步54ed9fe，
uv sync --locked通过，受控启动PID15469；注册源码checkout原clean，fetch/ff-only同步相同提交。
没有改变原Coder工作区、Task批准源或旧审批。

公开新PROPOSE_EXECUTION_BASELINE为operation_315f1bab48d195d8138140366e264e99，
idempotency_key=k1-20261012-baseline-54ed9fe-preserve-v1，原Task revision2、原attempt3 work、
source9cccb5b、父checkpoint ea13981...，target54ed9fe8875150c9783ddeceb9ff0b04324bf39e。
05:20:34.753574Z仍FAILED/COMMAND_REJECTED：历史 claim 没有可验证的调用或执行前停止记录。
没有产生可批准计划，未执行基线PAUSE或RESUME，原分支和完整dirty进度保持。

这说明通过的隔离public知识失败用例尚未覆盖生产的联合父/恢复Task知识作用域组合。
作者暂停runtime-only新功能，继续只读定位精确未覆盖历史claim及可信knowledge lane；
不能以枚举任意lane、缺start、补造stop或改SQL绕过。仍须加入真实公开联合恢复回归并独立审查。
生产K1尚未完成；隔离测试DONE不等于本需求交付。

## 精确父知识作用域发布后的容量核验（06:10 UTC）

0434f0019e78a63f89e4112e7ba06d620f84b073已独立审查、push main并受控部署。
全局338条Operation中active_complete=true、active=[]，PID15469受控stop确认全部保存和结束；
uv sync --locked通过，PID38551受控start，注册源码clean后fetch/ff同步0434f00。
原Coder工作区、原Task和全部旧失败历史保留。

公开新proposal operation_318977ea26f7feb68371dc94e7a5dcf4，目标0434f00、preserve_draft，
仍精确绑定原父checkpoint ea13981...、Task revision2、attempt3 work和source9cccb5b。
06:10:59.037389Z FAILED/COMMAND_REJECTED：容量停止记录与真实 claim、原权限或工程输入不一致。
此轮越过原历史知识记录缺口，尚未生成可批准计划；无PAUSE/RESUME、Git移动或模型调用。
继续按真实capacity receipt7881...逐字段只读诊断claim/权限/工程输入，不能删除校验让它通过。

## 不可变 claim 修复发布与真实提案通过（07:06 UTC）

`f91f33a857b34fb5e3f613f655559f676df8a466` 经独立审查和增量验证后已推送 origin/main。
发布前全局339条Operation，`active_complete=true, active=[]`；PID38551经受控stop保存
全部操作与写入、确认执行器及索引结束后退出。维护main ff-only、uv sync --locked通过，
受控start得到PID802。注册源码checkout原clean，fetch/ff-only同步同一提交。
没有手工更改原Coder工作区、业务草稿、旧Task/审批或生产SQL。

原父checkpoint ea13981...、原Task revision2、attempt3 work、source9cccb5b，公开
PROPOSE_EXECUTION_BASELINE `operation_6950c8cbfc6b0b6b9bdf60df2bf373ce`，
idempotency_key `k1-20261012-baseline-f91f33a-preserve-v1`。07:06:20.186341Z
SUCCEEDED，封存方案 `27a27e4202c1759f785ada2770e71dae1fb689daffcabcac8a130fec9cf1e7a1`。
完整typed model与integrity校验通过，target与prepared source均f91f33a、preserve_draft、
conflicted=false；原12个合法草稿文件、Task/branch/worktree保留。精确capacity receipt仍7881...，
continuation current=next attempt3、uninvoked、reservation_already_applied=true，没有退款。

规范变更为11个Trellis文件，change SHA
`ed09b4178a2b3930fd81548ac06716828bfb30343dcd22585e7fb97d7c112b25`。
需核对完整公开规则正文后执行精确PAUSE，再独立RESUME。此时仅提案通过，尚无本轮执行批准、
Git移动或新主Coder调用，K1未交付；不以Operation成功代替独立QA/Review。

独立只读最终审查通过：原SQL Task/revision/唯一等待/no-active-claim、完整quiescence与
capacity、两份真实Gitcapture和全inventory、sealedepoch全Git正文，以及11条公开规范
GET完整before/after/delta均一致。检查脚本
`/tmp/ase-k1-f91f33a-plan-readonly-review-20261012.py`；无生产写、审批或模型调用。

依用户既有代理工程审批授权，公开EXECUTE_EXECUTION_BASELINE
`operation_c80e807fc4eff430e0f58aebc2b50017`，精确plan27a27e42...、规范change ed09b417...、
continuation_mode=pause；07:16:02.204246Z SUCCEEDED。绑定
`733f0ada672a8c3deace417ef2e77cca0398d7d3de5d65a10bec635c74d2c052`，原分支/工作区保持，
新source=f91f33a。fresh公开summary确认Task仍IMPLEMENTING/revision2，原attempt3 work
WAITING_HUMAN/EXECUTION_BASELINE_PAUSED，disposition
`41a71f3b6f52e1132ba356901ea092c5d2f51bfee7d137a6cf50802b921efd66`；没有因此启动Coder。

独立明确继续使用fresh binding/disposition/source，公开RESUME_EXECUTION_BASELINE
`operation_9d60ce47bda23ddc9dd58813b43ad721`，07:18:19.022027Z受理，07:18:26.156345Z
RUNNING。这只是继续操作进入处理，主角色调用、输入容量、候选与独立QA/Review尚待核实。

07:21:50.178959Z该RESUME FAILED/COMMAND_REJECTED，原错误
`recovery record already has different content`。真实公开knowledge_intent路由
gpt-6.1-sol于07:19:57.948196Z开始、91405ms后SUCCEEDED；不能将其当成主Coder开发。
07:21:35的preflight WAIT_ENGINEERING显示注册MySQL镜像当前不可用；随后两次独立重查
READY。这只能证明各次观察，不能反推首次等待不合理。07:20附近一次summary
503 TEAM_UNAVAILABLE，独立随后只读重放25Task/2Request PASS；无原堆栈，不宣称固定reader缺陷。

独立SELECT-only确认确定写侧缺陷是 `_resolve(automatic=True)` 使用仓库固定
`delivery-wait-authority`；其scope.json已合法绑定旧Task8ca06...，新Task455883...冲突。
scope旧SHA0d73eca6...、当前7ee97ec6...，唯一delivery_id不同；旧文件不能覆盖。
独立Trellis10-12-task-wait-authority真实复现同RecoveryConflict RED5.57s，再以Task hash
隔离本地root，保持共享Team账本计费和exact replay。8增量PASS29.72s、静态/独立审查PASS，
提交ad898e5。原审批、基线绑定、失败Operation、Task和草稿完整保留，发布后从原等待入口处理。
