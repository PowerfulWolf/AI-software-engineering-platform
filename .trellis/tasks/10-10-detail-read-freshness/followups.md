# 独立后续问题：Product 讨论在读取故障时暂不可见

## 精确复现（隔离 Chrome fixture）

Requirement `WAITING_PRODUCT_APPROVAL`，已有Product对话，输入“诊断保留的产品草稿”，再令
GET `/api/v1/team?project_id=...` 返回503/`TEAM_UNAVAILABLE`。故障时原textarea的
`isConnected=false`，`value`仍为该草稿，`discussionFormCaches.size=1`。恢复相同Team/
Project/checkpoint/stage后，textarea重新连接，`same=true`，草稿值完整相同。

仅fixture GET，未调用生产或模型。临时Node/Chrome诊断一例通过；没有把这个既有行为当作
本任务已修复，也没有为通过freshness测试改动现有门禁。

## 根因与实际影响

`app.js::requestOperation(panel, request, discussionSection)` 的首行
`if (!canControlCurrentTeam()) return;` 在Team读取故障时直接跳过整个讨论表单。后续
`buildDetail`增量协调于是把表单从可见DOM移除；其余讨论和文档仍可见。

`discussionFormCaches`仍保存原form及draft，不是数据清空。相同精确讨论key恢复后复用原
form，草稿可重新读取。但故障期间用户看不到正在编辑的内容，焦点/选择会丢失，也不能
复制或继续整理草稿；这仍是不合理的只读故障体验。

## 建议独立任务边界

把编辑草稿与提交资格分开：保持相同Team/Project/Requirement/checkpoint/stage的缓存form
可读可编辑，同时所有提交/截图上传与旧callback继续核对当前控制资格。当前精确事实变化
仍按既有discussionKey失效和显式用户选择处理，不为了保留可见表单复用旧批准。
应独立测试Team busy/unavailable/timeout、失败期间选择/焦点/截图草稿保留、旧callback零
POST、相同事实恢复、Project/checkpoint变化和新操作已受理，不能仅删除入口门禁。

本freshness任务只覆盖已有composer草稿保持，未声明Product讨论故障可见性已修复。
