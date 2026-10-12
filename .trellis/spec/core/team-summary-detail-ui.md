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

Good：状态快速独立更新，用户稳定阅读完整报告并审阅当前规格后明确批准。Base：首次完整
历史仍有成本，显示真实loading/旧正文时间。Bad：strip全snapshot冒充省装配、空数组冒充
没有历史、合并旧detail header到当前controls、读取metadata就启用审批或丢弃8条外返工。

Tests：`team-summary-reading.test.cjs`真实HTTP/submitOperation边界，browser同名文件真实
DOM/文本选区/390px/14轮/失败与关闭测试；readiness/ui/operation-summary-reading/
preparation-progress/engineering-wait/knowledge-gap回归。仅增量，不运行全量。

## 存量数据处置 / Rollback

无数据库、journal、Task、Operation、审批、预算、Context或工作区迁移。全部历史保留，
原需求加载兼容资产后即可读取；服务资产在空闲受控维护窗口部署。回滚新增客户端读取
模式可用旧v0.2full，既有精确授权、完整事实与独立验收不改变。
