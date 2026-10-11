# 设计与核验

## 契约

`ProductionTeamReader.snapshot(project_id) -> TeamSnapshot` 仍只读最新真实事实。`JointJournal.current/history` 仍读取完整有序历史并隔离返回对象。`GET /api/v1/team` worker锁覆盖真实读取和序列化，取消HTTP不释放未完成工作。新旧响应结构不变。

前端单页维持一个 refreshFlight，Project意图只保留最新值；定时更新由完成时安排而不是固定时钟累积，busy/timeout只影响自动重试节奏，不建立可信新事实。独立恢复准备进度不等待Team刷新。

## 方案选择

现有 `_JointHistorySnapshot` 与 `_TaskReadSnapshot` 已分别复用同观察内的联合历史和精确Task投影，不再重复添加同类缓存。实测工程历史读取对同sidecar每个Task重新解码完整等待、preflight与disposition前缀，然后过滤到本Task，因此新增 `EngineeringHistorySnapshot` 只在一次Team snapshot内保存这些已验证typed事实。每Task的intent、scope、policy、独立引用和决定匹配仍逐一核验；下一snapshot重新读取所有源文件。缓存不放到reader实例，不跨请求，不保存Task状态/授权结论。

前端保留现有latest-intent串行 `refresh()`。唯一自动Team timer在整个刷新结束后安排，成功后5秒；连续Team busy/timeout为10→20→30秒，辅助Operations错误不影响Team退避。显式刷新和Project导航清除待执行timer并即时进入现有串行流程。恢复准备仍独立5秒通道。不会通过跳过退休历史、只读最新文件、信任mtime或缓存权限换取延迟。

不提升JointJournal到reader实例：原有512条缓存缺少足够严格的byte/heap上限，真实项目可能常驻数百MiB；本任务不扩大这类对象生命周期。

Engineering helper的整个观察总预算为512条、16 MiB序列化UTF-8模型字节、128个prefix、64个store；这不是Python总heap上限。超出优化预算仍完整读回与校验，不截断历史。真实共享wait/preflight ledger约0.55 MB。

验证后的性能结论收窄为重复IO与解码工作减少，不承诺总读低于5秒。串行fresh-process cProfile旧7.112秒、新8.058秒，未改动Joint/baseline耗时有较大差异；工程历史扣除嵌套baseline约1.21→0.65秒，但总耗时未证实改善。完整历史与基线校验仍是独立待优化成本，不以当前调度修复代替它。

## Good / Base / Bad

Good：同一只读观察内复用精确核验事实，下一观察仍检查完整变化；慢请求完成后才安排下一自动读取。

Base：首次大历史读取仍可能较慢，页面显示正在刷新并保留阅读状态。

Bad：HTTP取消时提前放开worker锁、缓存整个snapshot、忽略旧历史篡改、并发读取多个Project、将已分配模型视为已完成调用。

## 回滚

代码回滚，无数据迁移。生产部署等当前操作和全局claim空闲，走受控服务关闭与启动。
