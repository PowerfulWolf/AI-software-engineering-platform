# 实现与边界

基线 `ab5dead`，当前main checkout单Agent实现。没有使用生产Coder/QA/Reviewer派发，
没有修改任何运行中的Requirement/Task/Operation或审批。

## 最小修复

1. `redaction.source_inspection_scope`只保存纯扫描结果；完整正文和路径精确相等才复用，
   patch与source隔离。512条/16MiB key预算触顶时不缓存，实际扫描不省略。
   ContextVar在同步读取结束或异常后reset；嵌套同读共享，独立线程和下一次读取不共享。
   无法编码成UTF-8的key不缓存，不给旧扫描器新增拒绝语义；过长key不先分配大型编码副本。
2. 正式Team snapshot、工程history和Operation读取进入该有界scope。工程history只获取
   一次bindings，完整timeline与精确审批/来源校验保留。
3. 既有exclusive flock内，idle claim每次重查全部相关目录/完整JSON bytes，只有与已完整验证
   的无QUEUED清单相同才跳过模型重放。清单改变回原全历史校验；记住idle前再次核对清单，
   publish使其失效。public list/get不使用这个idle结论，不新增持久化索引。
4. 前端按固定机器码区分Team busy、40秒deadline和不可用。超时优先，含错误响应body挂起。
   只显示固定中文；保留旧snapshot、阅读DOM、草稿与既有控制权限门禁。
   Team已成功而辅助分支失败时不给Team错误归因。初始busy的placeholder参与增量签名。

## 跨层与复用核对

- Utility→capture模型→工程/Operation store→Team reader→HTTP→browser：未更改wire或模型字段。
  复用的是纯函数输出，不是审批、领域对象或Task状态，API仍安全fail closed。
- 原worker-owned Team读gate保持；浏览器取消仍不是后台worker停止事实。
- idle优化仅在FileConsoleOperationStore中；InMemory实现本就不解码文件历史，无需镜像优化。
  没有添加另一个队列、派发路径、全局Team cache或手工领取。
- `redact_text`仍为通用脱敏入口；完整code/patch扫描共用原检测规则，不复制供应商/secret规则。
  源码、计划、baseline required Context及审批读取继续完整校验。
- 正式规范/相关思考指南已同步；本仓库没有生成的spec/template镜像。

## 红绿信号

旧实现的重复idle模型重放、重复bindings读取、重复相同源码AST扫描和busy分类定向用例先红。
补充的503错误body超时用例先报告普通不可用而失败；改为abort优先后通过。
补充的非UTF-8 key用例先被缓存记账抛异常；改为不缓存后恢复原语义。
浏览器真实验证busy后旧文档保持同一DOM/open，恢复后next_action更新。

## 存量与回滚

无需改库、补证据、改hash、重建需求或自动接续。源平台15,935个JSON文件摘要清单未变。
服务仍运行旧实例，加载必须通过空闲受控重启；浏览器刷新后使用新冻结资产。
回滚代码并受控重启，只恢复旧读侧成本/提示，不改审计、预算或审批。
