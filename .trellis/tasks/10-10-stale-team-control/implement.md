# 实现与边界

- Team 读取新鲜度进入 `deliveryControlUnavailableReason` 和 `pollingControlFacts`；旧 snapshot
  保留阅读，但不能授权准备/批准/处理/继续。中文提示说明暂停操作、自动重读和保留进度。
- Team 分支失败立即发布门禁；不等待独立 Operations/Console。只处理当前目标且尚未发布
  Team 的失败。成功后的辅助故障不误标 Team。总 catch 只更新读取展示，不伪造执行结束。
- 失败与相同内容成功恢复均增量更新详情；开放的 composer 保留原节点和填写草稿。
- 当前 Requirement 知识解答使用不可变 Project/需求/checkpoint/full gap 绑定；批准入口纳入
  统一按钮同步门禁，同时 handler 在 hash 前后两次重新校验 exact 未解决 gap。
  pending 详情 GET 只给匹配当前绑定的需求补充已验证 view，exact gap ID 纳入缓存键。
  正文/问题/答复草稿保留；独立知识管理和设置不受扩展门禁影响。
- 节点状态、durable Operation、模型进度、角色 verdict 和工程权限均未修改。长时间运行已有
  专用说明与防重复门禁，本轮未增加未经事实支持的百分比、完成时间或额外恢复状态。

## 审查与存量

独立 reviewer 审查通过，并参与 Team/辅助完成顺序与 hash-await 竞态核验。当前生产 ASE 由主代理管理，
此任务没有 POST、审批、重启或数据库操作。原 K1 Requirement、Task、分支、现场与历史均未变。
兼容前端加载后轮询失败自动暂停人工决定；读取恢复后在原需求检查/操作，不需要重建需求。
