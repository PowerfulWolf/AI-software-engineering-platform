# Console 读取延迟与繁忙交互

目标：原 K1 的当前摘要、完整详情可可靠读取；繁忙与真实核验失败有明确区别。
范围：只读 Team Reader 和浏览器读取调度；不修改 Requirement、Task、审批、队列、工作区。

验收：
- 固定 TEAM_READ_IN_PROGRESS 仅作有总时限和次数上限的浏览器重试；真实损坏不重试或成功降级。
- 详情和最终精确 source fence 不装配响应未使用的其他 Project 统计。
- 同一 SQL 观察中，选中 Task 从 compact 到完整正文不重复构建已经核验的工程状态。
- 保持完整正文、所有历史、首次版本拒绝与正文读取后的 fresh source fence。
- 无并发 worker 扩容、跨 HTTP 授权缓存或 durable facts 写入。
- 增量 Python/Node 回归、Ruff/mypy 和真实只读耗时前后比较通过。

回滚：恢复读取代码；不改写任何历史数据。
