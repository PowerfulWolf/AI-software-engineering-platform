# 后端当前摘要与完整详情

## 范围与签名

`ProductionTeamReader.summary(project_id: str | None = None) -> TeamSummary` 与
`detail(query: TeamDetailQuery) -> RequestDetail | TaskDetail` 为只读新端口。
旧 `snapshot(project_id) -> TeamSnapshot(v0.2)`、原 wire 和 Schema 不变。

`TeamSummary(v0.1)` 保留 Team/Project/Agent、全部请求和任务卡片。
`RequestSummary` 显式包含 `RequestView` 除 `dialogue/documents` 的全部当前字段；
`TaskSummary` 包含 `TaskView` 除 `documents/timeline/execution_history/runs` 的全部当前字段。
每项 `detail_source: TeamDetailSource` 只作为读取定位，不是审批或 READY 证明。
不返回假装已经读取的空正文数组或无独立来源的正文计数。

## 精确定位

Source 含 `team_id/project_id/request_id/resource_kind/resource_id`、
`requirement_checkpoint_sha256`（当前 owner Request）与 `resource_checkpoint_sha256`
（Request 与前者相同；Task 为 native checkpoint）。Task source 含原 `work_kind`。
有实际 SQL 交付 Task 时，`task_id/task_revision/task_intent_sha256` 必须完整。
预派发无 SQL Task 时三者皆空，不能制造 revision。
候选验证使用真实 reservation `task_id/source_task_id/verification_plan_sha256`，
revision/intent 为空，不能把隔离的 reservation identity 当作普通 Task 状态机。

Source 的必填 `resource_state_sha256` / Query 的 `expected_resource_state_sha256`
只用于当前正文版本 fence。Task 绑定已核验当前timeline和真实route digest；候选验证额外
绑定plan/authority/invocations/completion/SQL release与放弃/supersession，保证同阶段封存结果
变化也刷新详情。不制造SQL revision或恢复许可。原生Request选中详情必须读取实际完整
ProductSpec JSON并核验native sidecar/repository、request/preparation、Product checkpoint与
Spec ID/digest；缺损正文503，不用空引用冒充已读，旧full保持原引用。

`TeamDetailQuery` 使用 `kind/id` 与显式 Team/Project/owner identity，所有版本字段使用
`expected_` 前缀；两个 checkpoint 分别明名，不接受路径或自由 URI。
严格拒绝未知/重复 query key、部分 Task 三元组、错误 variant 字段、空 hash 与非法 revision。
`RequestDetail|TaskDetail` 的 `kind`、`scope` 与完整 `resource` identity 必须一致。

## 读取与生命周期

新 GET `/api/v1/team-summary`、`/api/v1/team-details`；`/api/v1/console` 只在 reader 同时
实现两端口时声明 `team_read_contract_version=v0.1`。共享原 worker gate，仅完全相同的
`(mode, project, complete typed query)` 最多两个额外 waiter 可合并。取消 HTTP 不提前释放
实际同步 worker；每次成功或失败释放临时大模型，不缓存成功权限。

共同装配仍完整验证当前 Team/Project/native/joint chains、owner map、SQL、当前执行与
候选所需 artifacts/receipt/engineering facts。摘要从装配开始跳过 pretty document/dialogue、
run 展示和旧 Task 完整 history hydration。详情只为选中资源装配完整正文与历史，当前标题
不会通过详情回填前端控制。读取前后重新核对选中 checkpoint/identity，漂移中文 409，
未知/删除 404，损坏/不可读 503，不返回部分成功。

## 验证矩阵

| 场景 | 预期 |
| --- | --- |
| 同一 fixture 的旧 full 与 summary | 每个当前字段相等，原 v0.2 Schema 不漂移 |
| 大正文及多轮历史 | summary 无正文且未调用旧 Task 完整 hydration；selected detail 全部保留 |
| 外部 Team/Project/owner、未知/删除或版本漂移 | 不返回正文，固定中文错误 |
| symlink/坏摘要/错误链 | 完整校验拒绝，无部分成功 |
| 同 query / 不同 mode或resource版本 | bounded join / 原单 worker 忙拒绝 |
| 取消、失败、完成 | worker admission 持有到真实结束；大模型不跨 HTTP 保留 |

## 存量与回滚

无 SQL/journal/Task/Operation/审批/预算/worktree 迁移。全部历史仍可经详情与旧 full GET
完整读取。空闲受控加载版本后刷新原需求即可；本实现不操作生产。回滚新增能力和端点，
恢复旧 full，不重写存量事实。仅增量测试，全量测试由用户决定执行。
