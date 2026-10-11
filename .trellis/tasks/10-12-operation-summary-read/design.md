# 技术设计

## 阅读协议与权限隔离

新增严格OperationSummary/Scope/Query/Page/Cursor模型和四份静态Schema。独立GET `/api/v1/operation-summaries`，通过optional runtime能力与console feature manifest v0.1启用；旧setup或客户端完整接口不变。

摘要只含短文本、状态/作用域/身份与用于定位完整详情的digest/task/work字段，不含intent、patch、完整plan、approval正文或READY执行决定。默认25最多50，requested_at+ID降序，完整scope active≤64；response≤256KiB。cursor绑定完整inventory/scope/pageSize/sort与精确anchor，变化409；ETag只有重新核验bytes且能安全构造完整page才304。

## 完整bytes与有界cache

FileStore每请求在shared flock下读所有编号history文件完整bytes，保持regular/no-symlink/16MiB单record边界，再形成每Operation与root inventory。只在per-operation completebytes inventory相同复用OperationSummary。miss/变化走原 `_current` 完整Schema/hash/sequence链校验并再次hash确认读期间未漂移。whole-call source_inspection_scope允许同次纯文本校验复用，不跨请求保存完整内容。

cache由独立锁串行维护，最多512entries/2MiB serializedsummary+identity，不持有ConsoleOperation/FullPlan/authority；overflow只增加full replay，无列表裁剪。旧GET/mutation/claim/approval不读cache。summary scope须验证submitted/result一致与当前Team，foreign records在filter之前拒绝。

## 验收与风险

先红测试完整分页、旧active第一页之外、cursor漂移、same-size/mtime历史+ETag篡改、全chain损坏/links/oversize、新record、failed replay、scope隔离、512/bytescache限额、fullPlan weakref释放、Schema equality/wire。旧transport/core/idle/budget/scope做兼容增量回归。

冷读完整验证较慢是已知限制；常态warm不decode完整history对象。serializedcache预算不是Python总heap保证。summary不解决恢复原生事实核验的其他热点；必须单独测量。前端迁移独立worker负责，集成时继续要求审批display/submit前fresh fullGET。

## 存量与回滚

无需DB迁移或改写任何事实。部署等待无活跃生产Operation/role执行的受控维护窗口；不能热改生产主仓。撤回新增endpoint/cache/feature+前端能力即可回旧GET，保留全部原Task/Requirement/approval/verdict/queue/历史/现场。
