# 需求确认及执行可见性

用户反馈：需求恢复实现后看不到此前问题和代理答复；显示实现中但模型调用列表为空，
难以判断是否卡住。生产 API 已确认 knowledge resolution 99f12413 存在且 is_current=false；
前端只在 WAITING_HUMAN 或 Design recheck 时挂载历史区，正常恢复后入口消失。
当前 Coder 的下一代 lease 有效，14:09Z 仍修改测试；Operation 的 model-calls 仅是完成的
structured stage 诊断，Codex delivery 角色使用独立完成 route 记录，空列表不等于零调用。

目标：所有需求阶段都能按需查看持久化问题与确认历史；历史答案只读、不要求重答。
明确显示从 role_queue 导出的有效当前执行和心跳，并说明调用记录覆盖范围；不虚构
实时 provider 活性、调用次数、实际模型或 token 使用量。失效/关闭 lease 不渲染正在执行。

范围/允许路径：team_view/app.js、tests/team_view 的定向 Node 回归、本任务、
.trellis/spec/core/product-failure-diagnostics.md 和 live-team-view.md。
无 Schema/后端状态变化，不修改生产 Task/Operation/knowledge resolution。基线 fa3c96f。

验收：DELIVERING/INTEGRATING/DONE 均能展开已回答记录；WAITING_HUMAN→DELIVERING
即使 checkpoint 相同也不得缓存旧待填表单；安全 textContent 渲染；空/错误历史显示明确。
有效 RUNNING lease 显示角色/心跳；过期、WAITING_HUMAN、CLOSED 不声称执行中。
运行中空诊断区说明已完成与当前执行的区别，提供仓库任务记录入口。
仅跑 knowledge-gap/delivery-status/UI 相关增量测试；独立 QA/Reviewer 检查。

存量处置：只读展示既有 resolution 及有效 queue，无需改库。静态资源更新可由普通刷新
加载，不重启活跃 Coder。回滚前端代码到 fa3c96f，保留所有事实。
