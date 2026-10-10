# 过期交付失败通知

## 问题

同一 Project/Requirement 已通过新的 CONTINUE_DELIVERY 操作生成当前恢复待批方案后，
更早的 PRODUCT_APPROVAL INTERRUPTED 仍被通知筛选保留。用户关闭当前方案提示后，
旧失败逐项回流为模态遮罩，阻挡读取和操作当前需求。

## 目标与范围

只修改 `renderOperationStatus` 的通知筛选：同一 Project/target 的后续需求工作流操作，
即使 action 不同，也替代较早 FAILED/INTERRUPTED 的即时通知。当前待处理结果仍可提示，
关闭后不因轮询重新弹出旧失败。新的失败、其他 Requirement/Project 与无 target 的独立管理
操作保留既有提示规则。较新的工程调查也可替代旧即时通知；需求详情仍展示真实当前阻塞，
通知筛选不推断交付已恢复、不修改后台状态，不按每个 action 添加恢复例外。

完整 Operation 历史、需求详情、错误、审批及后台状态不改变。通知消失只表达当前提示已被
新操作替代，不表示旧错误从未发生，也不授予继续或批准权限。不修改准备观察与其他应用代码。

## 验收

1. 红测复现旧 PRODUCT_APPROVAL INTERRUPTED → 新 CONTINUE_DELIVERY SUCCEEDED 且待审批，
   旧即时失败提示被清除、轮询不回流，当前 pending approval 仍由需求详情精确方案卡呈现；
   待审批方案本来不弹全局通知，不能为本修复另加弹窗。
2. 已展示的旧失败在新操作到来时被清除；新 FAILED 仍提示，同 action 重试保持原行为。
3. 不同 Project/Requirement 不互相取代；无 target 的独立管理操作不被无关交付操作隐藏。
4. 未修改 operations 输入对象或历史字节，不产生 POST 或隐式审批。
5. Node 定向测试与隔离 Chrome `browser/notifications.test.cjs` 通过；真实 CSS 遮罩关闭后
   可点击需求，保留展开内容和草稿。只跑增量。

## 存量、加载与回滚

无需改库或迁移。加载兼容前端资产并刷新即可按原持久化操作重算提示；旧审批与完整历史保持。
回滚本次通知筛选与测试后刷新，不修改 Operation、不重启角色、不重复审批。
