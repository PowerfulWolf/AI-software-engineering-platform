# 实机部署与原 K1 接续（2026-10-10）

运行时代码已提交为 `a618668`，前端旧状态门禁为 `4bf596d`；两者已推送 origin/main。
通过受控服务脚本完成排空、保存、旧实例退出与新实例启动（PID 21248）。Console
ready=true、contract=4；HTTP app.js/style.css 字节摘要匹配已提交代码。
注册 clone 只 fetch Git objects，未改其 primary checkout，未手工改 Coder 分支。

## 公开存量更新

- 原 Requirement：`delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`
- 原 Task：`task_dc5cf0aee44e5ffe0cb600557204e0d0`
- 原分支：`ai/feature/k1-auto-knowledge-20261005`
- proposal：`operation_1cacb81f062eeda8b15b967fe5c9a419`，SUCCEEDED，75.227 秒。
- plan：`43c9d9c3b540e6bec08c380b914b30d043ca18e11a0c26f9b6ce9234a7b3872e`。
- 从公开 native-rules GET 审阅 incremental-polling/read-memory-lifecycle 两项封存差异，
  typed inspection 校验通过；change `e1ef5df82283e342234f5b13158c044843487e1bd3f3a611fffa9e686e980839`。
- execute：`operation_40aad7e236793008130138926a3c127f`，明确 PAUSE，SUCCEEDED，63.79 秒。
- 当前 binding：`b583b31278667f794753bb4c36f5cda4df3b92858888991690326839a46d6c25`。
- execution base/source：`4bf596d5ed487b96c1fbfbee892bdfba58457e1d`。
- 完整保留补丁 SHA：`fa62ab023ca1e6096ca58cb1905d26cc1284fb05da702ea13763fc653db871df`，
  342336 bytes、27 文件，与前次保留内容一致。
- resume：`operation_7b779aaf66c87cc8b486eba3b7ec378a`。从最新公开快照绑定 exact
  Task intent/revision、WorkItem、source、binding、disposition，提交用户委托的明确继续决定。

前一次 proposal/PAUSE 为 264.509/243.869 秒，本次为 75.227/63.79 秒。目标、绑定链和
在线负载不同，这些是实际单次观测，不是严格同输入性能比较或通用延迟保证。

## 当时的启动核对

公开 Team 确认原 Task、attempt 8 的同一预留 WorkItem 已 RUNNING，LEASE_VALID且心跳更新；
原暂停原因撤销，需求读侧呈现 Coder 执行中。没有重新创建需求、重置额度、直接改库或伪造 verdict。
平台修复的增量测试通过不能当作原 K1 完成；这段记录仅说明当时 Coder 已启动。

运行期间 operation model-calls 为空不能证明模型未启动：该端点的完成记录和原生执行事实是
不同入口。领取角色后的上下文/知识准备也属于 Worker 范围。只核对真实元数据、子进程与心跳，
不得以空列表推断中断、猜测模型结果或读取私有思考。

2026-10-10 04:57:17 UTC 的独立只读正式记录核验确认知识准备已结束，主 Coder
已经启动：知识 Context 于 04:45:38.057794 封存，与 attempt 8 / checkpoint 17 /
dispatch 2 的真实 claim 匹配；intent 83.607 秒、assessment 190.197 秒，实际模型均为
codex/gpt-6.1-sol。assessment GAP 的 owner 是 REPOSITORY，允许 Coder 只读核实代码，
并非人工阻塞。主 Run 为 `run_3d2b9488c43b4eeb9e6dc6e08fd6f2f0`；invocation-start
于 04:50:26.745869、capture-start 于 04:50:49.090718 封存。PID 49774 的 PPID 为
21248、cwd 为原 coder-attempt-01；未读取 argv/environment/私有会话或干预进程。
这些记录证明本轮已启动，不能证明最终实现、验收或有效产出已完成。

浏览器认证不可用，前端已经验证真实资源部署和 Node 操作门禁，尚未完成真实视觉/焦点验收。
原 HumanActionEvent 的外部测试样例维护继续保留，不能把本案例报告为完全自治 ADR。

## 第 8 轮最终结果

本轮最终没有产出可接纳的候选实现。30 分钟本地执行窗口耗尽后，Runner 于
2026-10-10 05:20:49.304200 UTC 实际停止 owned PID/group 49774，returncode=-15。
可信 capture-stop 摘要为
`3536fb3c74c9f706a4bbbe98438f9b69a6a3181d7234def856c87d4f6cba7eda`。
完整草稿封存随后发现本轮新出现的、未经写入授权的 `.venv/.gitignore`，mutation
authorization 拒绝；route/invocation outcome 记录为 POLICY_VIOLATION，原 Task 进入
BLOCKED，revision=18、attempt=8，8 个 Coder 队列项均 CLOSED。公开 parent checkpoint 为
`1fd26bb247bac44b43aa89e2fe60908b75e03971de9be22ebcf9451f5be6a663`。

这次存在实际停止证明，但没有第 8 轮 interruption receipt 或 RunEvidenceManifest；
不能用第 7 轮 receipt 代替完整现场证明，也不能据此确认是哪条命令创建了环境。
原工作区、合法业务草稿和新环境文件均保留，未删除或改写。
原 Requirement 尚未进入 QA/Review，K1 未交付。后续修复需完整核验停止及 ignored
inventory、保留有效执行基线的 epoch 链，并由当前精确恢复计划继续同一 Requirement。
