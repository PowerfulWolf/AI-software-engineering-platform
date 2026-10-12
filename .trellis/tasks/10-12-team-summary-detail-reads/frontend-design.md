# 当前状态与完整正文的客户端读取

## Scope / Contracts

`app.js` 依据已验证 Console 的 `team_read_contract_version=v0.1` 选择新的 summary GET。
首次刷新共享一次 Console 能力读取；未声明能力沿用原 v0.2，已声明后的 summary/detail
错误真实展示，不能转读旧接口掩盖故障。正文不进入 `snapshot`，只持有当前 selection 的
一个完整响应。标题、状态与操作始终由当前 summary 与独立完整 Operation 决定。

`teamDetailSourceKey` 固定 backend-design 的全部 identity/version 字段。选中实体变化、
Team/Project/page 变化或关闭 abort 旧 HTTP 并增加 generation；所有 await 后重验 owner、
源版本和 selection，晚响应不发布。只把经过验证的 dialogue/documents 或 task 的
documents/timeline/execution_history/runs 提供给阅读投影，不合并旧 header/controls。
同版本自动 summary tick 不重取正文；新版本读取期间保留同实体的旧正文并就近说明。
坏记录/409/503/超时显示中文重读入口，不显示“没有产物”。关闭释放正文和 DOM 引用。

全部资源的必填 `resource_state_sha256` 是已验证语义事实的读取版本，随完整 locator
冻结并发送 `expected_resource_state_sha256`；响应 scope 必须精确一致。新增 QA/Review
记录即使 native checkpoint 和 SQL Task revision 不变也触发完整正文更新；heartbeat/as_of
不是此版本。不能用它代替审批/READY 或伪造 SQL revision，缺失/错误/旧版本均拒绝。

Product批准仅在当前精确源的完整ProductSpec正文已读取、spec ID/原事实digest/source URI
均匹配summary.product_spec_source后可用。点击前与所有异步Operation读取后的POST边界
再次核对；旧正文、空引用、改版或读取失败都不能批准。保留服务端精确checkpoint fence。
文档sha为原事实digest，不能拿脱敏正文hash重新解释。

## Validation Matrix

| 场景 | 验证 |
| --- | --- |
| 旧服务 / 新能力服务 | 仅原full / 仅summary，错误不fallback |
| 相同source多次刷新 | 一个detail GET，正文不进入snapshot，不比较全历史 |
| A→B、关闭、Team/Project/page切换后的晚响应 | 不发布，不恢复正文或权限 |
| source变更 / 409 / 503 | 保留有版本说明的旧正文，旧Product批准失效 |
| ProductSpec空正文 / id、digest、URI不匹配 | 零POST，完整正确正文才可明确批准 |
| 12+轮返工与多份文档 | 全部展示，不限制8条，不截断 |
| 同checkpoint/SQL身份但新增反馈 | semantic state变更，仅重读对应完整正文；旧state响应拒绝 |
| 当前摘要改变与完整详情旧header不同 | 当前标题/状态/操作来自摘要 |

Node fake HTTP/DOM跑真实app函数；保留现有readiness/ui/Operation/polling回归。
浏览器测试按可用环境实际报告；没有运行就不声称视觉通过。仅增量，无全量。

最终前端验证：6个Node文件128项通过；3个真实Chrome文件13项通过（含新版反馈变更的
第15条完整记录、选区/滚动/展开保留、390px与读取失败/关闭）。独立review另跑新Node
两文件21项与新Chrome4项，均通过。范围有重叠，不相加作为唯一测试总数。

## 存量与回滚

无SQL/journal/Task/Operation/审批/预算/工作区迁移。空闲受控部署后刷新原需求。
回滚客户端新读取模式仍可用旧v0.2端口；所有历史与精确审批保持。
