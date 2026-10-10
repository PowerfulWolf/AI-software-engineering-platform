# Coder 反馈接收只来自实际父产物

## 实证缺陷

appendExecutionArtifactDetails 只要 Coder 产物有 parent_artifact_ids 就声称已接收上轮 QA/Review
反馈。合法首轮 implementation-report 只有 plan 父产物，真实 app.js VM仍产生这句成功说明。
这会让用户误认为返工意见已交给 Coder。

## 范围与契约

- 只改该产物展示函数附近；不改状态、命令、权限、wire/schema或生产事实。
- 从包含当前artifact entry的同TaskView已验证完整历史解析 exact父ID、artifact URI、SHA与
  kind；不从名字/任意Task猜测类型，不解析raw模型内容。合法successor关联历史可识别。
- 只有父产物是已验证QA/Review报告时才说明收到反馈；不宣称已经解决或完成修改。
- 仅plan/input/checkpoint不说明收到QA/Review。未知、重复/冲突父ID保持中性未知。
- 历史标签和所有事实bytes不变；无生产API、数据库、候选工作区操作或提交。

## 验证、存量、回滚

先RED后GREEN：QA、Review、仅plan/进度、未知父、合法历史反馈与重复/冲突身份。仅跑独立
窄Node用例，修正已有浏览器正向fixture的真实artifact身份/摘要，保留原断言。无需改库；
部署后原需求/Task的完整历史只重新计算说明。回滚本次函数展示分支并受控部署即可。
