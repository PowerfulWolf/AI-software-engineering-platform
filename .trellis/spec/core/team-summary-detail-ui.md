# 当前摘要与独立完整正文的前端读取

## Scope / Signatures

`team_view/app.js`；后端新wire参见`team-summary-detail.md`（backend-design）。
旧v0.2 full端点保持兼容，新Console能力`team_read_contract_version=v0.1`只选择新读取。

```javascript
verifiedTeamSummary(value, target)
selectedTeamDetailTarget()                  // complete source key + selection owner
readSelectedTeamDetail({force = false})      // one exact selected body, 40s deadline
detailReadingItem(currentItem)              // body fields only, never old current header
clearTeamDetailRead()                       // abort, generation, release body
productApprovalReadReady(request)
requireProductApprovalRead(intent, expectedBinding)
withTeamRead(read, signal)                 // one page-owned GET/body/publication
waitForTeamRead(signal)                    // cancelable local wait, no snapshot
readTeamJson(url, signal, {detail, current, publish})
readCurrentTeamJson(url, signal, {current, publish}) // same finite busy policy for summary/full
waitForTeamDetailRetry(delay, signal)        // one bounded owner/deadline retry
```

## Wire / Current Authority

- `refreshSnapshot`共享一次Console capability读取给Team和Operation，声明新能力后读取
  `/api/v1/team-summary`。旧服务读`/api/v1/team`；新summary/detail发生错误不能fallback
  掩盖损坏。能力读取的await返回后先检查deadline是否已abort再启动Team GET，不能把早已
  触发的AbortSignal交给只订阅未来事件的reader，遗失timeout并堵住最新Project导航。
- 新summary禁止正文数组，即使空数组也不代表完整记录已读。逐条核对resource identity、
  Project/Team/owner、双checkpoint、必填`resource_state_sha256`、真实SQL Task三元组与verification独立reservation。
  旧snapshot shape不改变，前端`snapshot`仅保存收到的当前摘要；没有全体历史JSON比较。
- 详情query明名expected_requirement_checkpoint_sha256、expected_resource_checkpoint_sha256与
  expected_resource_state_sha256；
  SQL Task追加exact id/revision/intent，独立verification追加真实source/plan，空参数省略。
  响应的schema/kind/scope/as_of/resource和适用SQL identity匹配才发布。
- `resource_state_sha256`绑定已核验的当前资源语义事实，包括独立验证新增的 invocation、
  completion 和真实 route outcome，不以 heartbeat/as_of 触发正文读取。它进入 frozen locator、
  source key、query 和响应比对；QA→Review 或新增反馈即使原 checkpoint/SQL revision 不变也
  重读完整正文。缺失、错误 digest 或旧语义版本响应拒绝，不能伪造新 SQL revision。
- 完整正文只在独立的`teamDetailRead` owner中保存；`detailReadingItem`只读取request的
  documents/dialogue或task的documents/timeline/execution_history/runs。当前标题、阶段、
  执行、queue、预算、授权与控件来自fresh summary与既有完整Operation；旧detail.header
  永远不回填当前状态。DocumentView.sha256是原事实digest，不计算脱敏正文hash代替。

## Lifetime / Human Interaction

- 同一页面 full/summary/detail 的实际 GET 和 response body 使用一个客户端调度 owner。
  摘要保留原串行 refresh/latest Project intent；选中正文等待该次 HTTP 完成，不能与本页
  摘要争抢后端同一个 worker。辅助 Console/Operations/恢复准备保持原独立读取。
- 等待者随 AbortSignal 立即移除，不能把每次已取消导航永久挂在慢 promise 上。只有最新
  selection/source 发 GET；每次等待后仍验证 owner、frozen locator 和 deadline。
  客户端 HTTP 完成/abort 只释放客户端调度，不宣称后端 worker 停止或改变后端 admission。
- 摘要同样传入 `current: () => !superseded()`；在正文后排队的旧Project摘要醒来必须在
  GET前跳过，原refresh owner直接drain最新Project。已实际进入的旧GET仍完整读完，禁止
  将浏览器abort或新导航当作服务器已退休；只丢弃其过期发布。
- 正文仅识别固定 `error.code=TEAM_READ_IN_PROGRESS` 为外部读取繁忙：同一 frozen owner
  最多额外三次，分别等待1、2、4秒；40秒总体 deadline 仍有效。等待期间说明正在稍后
  重读，耗尽保留明确手动入口；不重复读取已成功的相同 source。`TEAM_UNAVAILABLE`、409、
  非法 JSON/正文/身份不匹配均不自动重试，不能以调度掩盖原错误。任何等待不恢复批准资格。

- 当前摘要/full 刷新同样仅对固定 `TEAM_READ_IN_PROGRESS` 做 1/2/4 秒最多三次额外重试，
  保留原 40 秒总 deadline；每次延迟及实际 GET 前核验最新 Project/Team/contract owner。
  各次 HTTP 完成即释放客户端读取 owner，辅助读取继续。重试耗尽才发布 busy；
  `TEAM_UNAVAILABLE` 立即沿原核验失败路径处理，无 fallback。刷新期间原控制门禁继续生效。
  `productApprovalReadReady` 仅表示正文已读，不代替 `canControlCurrentTeam` 的当前执行权限。

- 同selection/source自动刷新不重复GET。Team/Project/page/实体/selection revision或关闭
  改变owner，abort旧HTTP、递增generation；每次await后重验owner和source key。冻结
  locator副本，current source原地变化也不能改变原读的期望。晚响应释放value，不复活
  已关闭详情或清除新owner状态。
- 同实体source变化后独立重读，保留旧正文可读，标题区明确这是上次完整读取的正文；
  当前状态仍fresh。不把loading/409/503/timeout说成“暂无产物/历史”或新的交付BLOCKED。
  中文说明和显式“重新读取完整正文”入口就近可见；详情读失败不授权继续或重建需求。
- 完整14+轮QA/Review返工与报告保持，无8条限制和截断。原keyed DOM/章节保留展开、
  选择、滚动与草稿；未变化summary不重读body。Task原暂停阅读只影响可视正文，后台事实
  继续读取；关闭或跨scope不能保留暂停授权。

## Product Approval

ProductSpecSource仅提供读定位；必须等当前精确完整正文读取成功，才能启用Product批准。
校验原spec digest/URI和真实身份：native用spec_id+正文id，joint用真实version+完整product
对象，不能为JointProductSpec伪造不存在的ID。原native空正文引用不算已读。
按钮闭包冻结checkpoint+ProductSpecSource，在点击前重验；`submitOperation`在异步完整
Operation recheck之前与actual POST之前再次检查。改版、读取失败、关闭/导航或消失的
body owner均零POST。服务端原exact checkpoint/spec批准仍是最终authority。

## Validation / Good, Base, Bad

| 场景 | 必须结果 |
| --- | --- |
| 旧full服务 / 新summary能力 | 原wire / 新wire；单次能力读取，无新错误fallback |
| heartbeat或相同source自动tick | 单次detail GET，正文不进snapshot，真实DOM/选区/展开保留 |
| source改变且detail503 | fresh标题/阶段，标明保留旧正文，旧Product批准失效 |
| A→B、close、Team/Project/page晚response | 无旧value或权限重新发布 |
| 14轮失败/返工 | 全部history与finding可读，无默认截断 |
| native id/joint version、digest或URI不符/空正文 | 批准disabled、旧callback与异步POST边界零写 |
| Console await前已经timeout，最新Project pending | 旧Team不开始无期限读，串行lane释放并读最新目标 |
| 本页摘要在读，打开选中正文 | 正文不并发GET；摘要完整验证/发布后仅最新locator读取成功 |
| 正文在读，自动摘要tick | 摘要等待；Operations等辅助读取继续；无本页跨mode busy |
| 正文持有→旧摘要排队→用户切Project | 旧摘要零GET；原HTTP真实结束后只读新Project |
| 摘要期间20轮选择/关闭 | 每次已取消等待者立即从Set移除；零旧owner GET或审批 |
| 摘要发布新的正文source | 等待中的旧locator不发GET；新source仅一次完整读 |
| 外部固定busy | 额外1/2/4秒三次；40秒总deadline；耗尽中文说明和显式重读 |
| busy后真实不可用/409/非法正文 | 停止重读并显示原分类；不发布正文、不恢复Product批准 |

Good：状态快速独立更新，用户稳定阅读完整报告并审阅当前规格后明确批准。Base：首次完整
历史仍有成本，显示真实loading/旧正文时间。Bad：strip全snapshot冒充省装配、空数组冒充
没有历史、合并旧detail header到当前controls、读取metadata就启用审批或丢弃8条外返工。

Tests：`team-summary-reading.test.cjs`真实HTTP/submitOperation边界，browser同名文件真实
DOM/文本选区/390px/14轮/失败与关闭测试；readiness/ui/operation-summary-reading/
preparation-progress/engineering-wait/knowledge-gap回归。仅增量，不运行全量。

根因是两个分别正确的客户端读取owner共用一个后端worker，后端的即时busy被正文永久
记录为unavailable；只修摘要五秒timer或gate释放并不能消除此交互。新增Node回归调用真实
`refresh()`，持有两方向HTTP、断言实际请求次数/新locator、abort等待Set和有限timer；Chrome
同文件覆盖真实用户打开、自动poll、完整14轮历史及busy后精确Product正文批准。客户端
abort只结束浏览器等待，之后若后端仍忙仍遵循同一固定busy有限策略，不改变服务读取安全。

## 存量数据处置 / Rollback

无数据库、journal、Task、Operation、审批、预算、Context或工作区迁移。全部历史保留，
原需求加载兼容资产后即可读取；服务资产在空闲受控维护窗口部署。回滚新增客户端读取
模式可用旧v0.2full，既有精确授权、完整事实与独立验收不改变。

## Canonical nullable identity wire (2026-10-12)

`DomainModel.to_wire()` omits None fields. Browser source/body comparisons for `task_id`,
`task_revision`, `task_intent_sha256` must normalize **both** operands with `?? null` in
`validTeamDetailSource` and `verifiedTeamDetail`; comparing undefined against one normalized null
rejects a valid full Team summary and leaves the entire page unavailable.

Legacy delivery/remediation may omit the whole Task identity triple; candidate verification has
real task/source-task/plan identity but omits SQL revision and intent digest. Identified delivery
and remediation keep their complete exact triple, including valid revision 0. Missing and explicit
null are equivalent only for nullable fields; real values, partial triples, owner, resource,
checkpoint, candidate source/plan mismatches remain rejected. No fallback full snapshot or relaxed
approval is added. `teamDetailSourceKey` already applies the same null normalization.

Regression: `tests/team_view/test_nullable_wire_ui.py` builds real typed Python summary/details
and calls `.to_wire()`, then feeds their exact JSON into shipped JS via
`tests/team_view/fixtures/nullable-wire.cjs`. It proves omitted keys before invoking JS and tests
both null representations and actual identity mismatches. Handwritten all-null JavaScript fixtures
alone are insufficient for this cross-language contract. No schema/store/data migration is needed.

## Reading identity survives temporary Console metadata loss (2026-10-12)

Scope: `team_view/app.js::refreshConsoleInfo`, `verifiedTeamSummary`,
`selectedTeamDetailTarget`, `refreshSnapshot`, `renderMaintenanceBanner`. No HTTP or stored Schema
changes. A verified `GET /api/v1/console` negotiates `consoleReadingIdentity={teamId,mode}` and
`consoleTeamReadContractVersion`; `consoleTeamId` and
`consoleOperationSummaryContractVersion` also retain the verified read scope. None is a delivery write grant.

On network/5xx/invalid JSON/invalid core metadata, keep the last complete reading scope and both
read protocols. Clear `consoleAvailable`, current `consoleMode`, `consoleDeliveryReady`, operation
contract and supported actions; set `consoleConnectionFailed`. Current delivery write gates continue to
require `consoleAvailable === true`, fresh Team/Operation facts and exact action support. In
particular do not null the identity but keep the summary protocol, and do not fall back from
Operation summaries to complete history merely because the Console connection failed.

Metadata publication is atomic after validating schema, Team, delivery readiness, mode and Team
read protocol. Only missing/null Team protocol denotes legacy full reads; an unsupported explicit
version is unavailable rather than a silent downgrade. An explicit 404 clears the read identity,
protocols and complete reading scopes. Successful Team or wire changes invalidate old complete
bodies; a different Team also clears Operation scopes. An initial metadata failure retains legacy
v0.2 dashboard reading compatibility, cannot accept an unsolicited v0.1 summary and cannot write.

`consoleInfoReadGeneration` fences both header and body awaits, including failures: an older
Console request may not overwrite a later observation. `refreshSnapshot` freezes negotiated
identity/version before queuing its Team GET and rechecks them before GET and publication. A
changed binding cannot publish an earlier Team response even when Project IDs are reused. Same
Team/source successful reads preserve the complete selected body and reading position.

A disconnected page last confirmed as inspection retains a banner explicitly saying “上次确认…
当前连接尚未确认”; it must not call the prior mode the current service mode. Successful metadata
restores the current banner/readiness; 404 clears it. Neither text nor successful GETs resume K1.

| Input sequence | Required observation |
| --- | --- |
| normal/inspection metadata200 → network/503/invalid JSON → valid same-Team summary | readable summary/body, all delivery mutations disabled, no full-history fallback |
| prior binding → response from another Team or altered checkpoint | reject; preserve prior reading without renewed control |
| initial metadata failure / confirmed404 | legacy full read only, no invented summary Team or write authority |
| valid new Team / explicit supported wire change | clear old complete scope; accept only new exact identity/protocol |
| invalid mode or unsupported explicit read version | no partial identity publication, no implicit wire downgrade |
| late metadata200/503/404 after newer observation | no overwrite of newer identity/readiness |
| held summary → independent Team metadata switch | discard old publication; controls remain unavailable |
| confirmed inspection → disconnect → reconnect | last-confirmed banner → current banner; no fake running/paused Task verdict |

Good: Team and bounded Operations remain readable through a control-plane interruption while
delivery mutations fail closed. Base: first-ever metadata failure can still show legacy read-only records.
Bad: a cleared control Team makes every later valid summary fail, or disconnected polls reload the
whole Operation history. Regression tests execute shipped `refresh()` with fake HTTP/timers for the
complete metadata/summary/Operation chain, assert endpoint counts, POST absence, retained body,
exact rejection, concurrent publication fences and banner wording. Canonical Python `to_wire()`
regression remains required for source identity comparisons.

Existing data: no SQL/journal/Task/Operation/approval/queue/budget mutation or migration. Deploy the
client asset during controlled platform maintenance and reload the page; keep the existing
inspection marker and demand pause. Rollback restores the prior asset and reloads it, preserving
all durable facts. This defect does not prove the cause of every historical production read failure.
