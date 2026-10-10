# 实现说明

`app.js` 的共享 detail freshness helper 为需求 masthead 与 Task 粘性 header 提供独立
只读提示。WeakMap 绑定实际展示内容的 Team/Project/实体与 snapshot 时间，renderView /
viewBlock 签名只协调提示自身。Team 读取 busy/unavailable/timeout 时用固定中文和
textContent 展示原读取时间；恢复或来源不匹配时隐藏，不新增 API 请求或写操作。

Task 阅读暂停路径只更新提示，保留旧正文及其来源时间；不冒用后台新 snapshot 的时间。
原有执行节点、审批资格与控制 callback 的精确校验不变。`style.css` 只增加紧凑蓝色信息
样式；读取问题不会变成新的红色交付阻塞事实。

`detail-read-freshness.test.cjs` 以独立 Chrome fixture 覆盖 RUNNING、BLOCKED 审批、Task
暂停、Project 切换和 composer 草稿；保留正文/选择与相对阅读位置，并验证恢复门禁、窄屏
排版及零写请求。最终结果和独立确认的既有回归失败见 `verification.md`。

本任务已进入 review，未提交、部署、重启或操作生产。后续 Product 讨论草稿可见性问题仅
记录在 `followups.md`，等待独立授权与任务后实现。
