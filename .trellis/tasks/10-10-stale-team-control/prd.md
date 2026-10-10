# 旧团队数据不能授权新的操作

## 目标和问题

Team GET 忙碌、不可用或超时时保留上次成功读取的需求和历史，方便用户继续阅读。
当前版本却仍允许基于该旧 snapshot 准备、批准、处理中断和继续，并且旧按钮 callback
仍可提交。独立 Operations/Console 成功不能证明当前需求事实仍有效。

## 范围与验收

- 明确中文说明当前团队数据尚未核对、页面显示旧数据、当前操作暂停；读取恢复后自动核对。
- 三种失败均撤销当前操作门禁，旧 callback 和直接 submit 均不发 POST；Project 切换门禁独立。
- Team 分支已失败而辅助分支仍在等待时立即撤销操作，不等辅助完成或 40 秒 deadline。
- 保留旧 snapshot、完整历史和正在填写的 composer 草稿；工程参考和已保存报告仍可读取。
- 增量渲染刷新失败/恢复提示；成功返回相同 Team 内容也恢复门禁，不要求切页或重新建需求。
- 辅助读取失败但 Team 已成功发布时不得误报 Team 失效。
- 当前需求知识解答也是人工决定；Team 失效期间保留正文和填写草稿，但暂停批准。
  提交前与异步摘要计算后核对当前 Project、需求、checkpoint、未解决的 exact gap 和门禁。
  不能只禁用按钮；旧 form callback、已解决或已替换的知识事项均不能发 POST。
  独立 Team/Project 知识上传、选择和设置不受此需求决定门禁扩展影响。
- 不改 Task/Operation/审批/角色权限或数据 Schema，不操作生产 ASE。

## 验证与回滚

只跑相关 Node UI/readiness/engineering-wait 回归、JS syntax 和 diffcheck，不跑全量。
真实浏览器视觉尚无验收能力，不能据 fake DOM 声称视觉通过。存量无 SQL/历史迁移；
在原需求加载兼容的新 assets 即可，失败期间不补造执行停止或批准记录。
回滚该 UI/spec/test 变更并刷新页面，持久化进度和历史保持。
