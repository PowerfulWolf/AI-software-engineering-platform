# 详情与轮询增量 fixture 对齐

## 目标与范围

两条独立复现的既有前端回归失败由fixture事实与实际调用约定不符导致，不修改生产
行为或减弱断言。Node计时器回调本身不返回刷新Promise，测试必须等待真实refreshFlight
后读取DOM；当前Task的Chrome fixture应绑定DELIVERING parent与current scope，而不是
把当前任务挂到READY_FOR_DISCUSSION且空scope的父需求。

允许路径：tests/team_view/ui.test.cjs的interval/DOM mock与对应旧文案和失效callback断言，
tests/team_view/browser/task-detail-reading.test.cjs的openTask，incremental-polling测试约束
及本目录。保留知识超时的单条文案更新。没有修改任何生产行为。

## 验收与验证

- 保留QA/Reviewer不同需求2条代表行断言与全部底层Task历史，不改collapse helper。
- 保留“当前进展”章节断言，历史Task的“当次执行结果”与完整历史展示不改。
- DOM fixture正确表达连接/断开；旧checkpoint按钮零POST，重新取得当前精确按钮才提交。
- 文案断言对应现有“待工程确认/原执行历史”；删除后当前卡片消失、操作历史标题保持。
- 跑上述两个目标文件；只做增量测试，无数据库/模型/生产操作。

## 存量数据处置与回滚

仅测试fixture，无存量迁移或服务变化。回滚仅撤销fixture对齐；生产历史和状态不变。
