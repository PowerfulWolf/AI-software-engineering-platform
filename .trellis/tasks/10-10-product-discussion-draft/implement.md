# 实现说明

只修改 `app.js::requestOperation` 的 Product 讨论相关分支。Product 表单不再因中央控制
暂不可用直接消失；非 Product 交付操作保持原顶层门禁。相同 key 的缓存 form 继续复用，
仅同步就近的“暂停发送，草稿仍可编辑、复制和整理”说明。瞬时读取问题不进入草稿 key，
Team 身份显式进入 identity/key，Project/checkpoint/stage/Operation/drift/budget 仍参与。

表单创建时冻结 Team、Project、Requirement、checkpoint 和 stage。`discussionFactsCurrent`
检查连接、当前缓存身份、中央控制、当前 Team/Project、最新相同讨论 key、工作额度与无
active Operation；所有截图写请求前和 Product Reply 前再次核对，旧 callback 或 await
之后事实改变不能继续写。请求只使用冻结的 scope/checkpoint；受理成功才清除原草稿。
Product 回复继续使用原 `onFormSubmit` / `runUiAction` 的进行中防重复。中断 Product
回复继续按钮也使用精确绑定与当前事实检查，并纳入同一 form 的 `runUiAction` 防止
Operation 受理响应返回前的重复 click；响应受理后继续由 active Operation 与缓存绑定拦截。

无 API/Schema/后端/数据库修改，不调整其他通知或审批权限；根代理在本函数末尾添加的
知识准备超时继续入口展示不属于本子任务，按共享 checkout 协议保留。
