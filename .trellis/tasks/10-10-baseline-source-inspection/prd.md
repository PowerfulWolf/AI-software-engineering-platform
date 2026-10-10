# 同步基线校验的有界源码扫描

## 目标

准备、执行、明确继续同一需求的基线方案时，重复嵌套模型校验会反复解析相同完整源码。
复用已有 `source_inspection_scope` 的纯扫描事实，保持全部原有校验、审计事实和旧 wire。

## 范围与已确认测试接口

- `ExecutionBaselineService.propose/execute/continue_execution` 的完整同步业务校验。
- 独立 `FileExecutionBaselineStore.plan/start/bindings_for_task/required_context` 读取。
- `FileContinuationStore.get_receipt/receipts_for_task` 完整递归读取及发布校验。
- 真实 Git fixture、真实私有文件 store 的增量性能契约。

## 验收

- 相同文本和路径的敏感信息 AST 扫描在一个同步调用中共享；独立调用重新检查。
- 有界缓存始终在成功/异常返回时释放，不跨 Host 后续模型启动。
- 大源码 fixture 的完整 bytes、SHA、角色权限、批准及新鲜 Git/文件观察不变。
- 改变文本/路径、篡改 digest、改变现场或错误批准依然拒绝。
- 不改 SQL、不发生产操作、不重启、不运行全量测试、不提交。

## 回滚点与存量数据

代码回滚只撤回 scope 包装，不改任何历史数据。没有 Schema/SQL/文件格式变更；
存量计划、receipt、binding、批准无需改写。恢复原性能开销是回滚的主要影响。
