# 流程节点展示

## 问题与目标

真实 ProductSpec 批准 Operation 已进入 DESIGNING 并处理知识核对/产物生成，但由于没有模型
心跳，页面把流程节点显示为“执行状态待确认”。应把流程处理事实与执行器 liveness 分开。

统一共享前端派生：蓝色表示本轮节点执行中；绿色表示阶段通过完成；红色表示阻塞、需确认或
待审批；灰色表示排队、重试、尚未执行或状态需核对。文字与 aria-current 一并表示状态。

## 验收与边界

- 已进入 Product/Design/Plan/Integration 且同需求同 Project 工作 Operation RUNNING，无当前
  durable wait、中断、过期 claim 或新角色失败时，流程/card/detail/Manager 一致显示执行中。
- QUEUED、READY/LEASED 及 RETRY_SCHEDULED 保持灰色，不推断模型已开始。
- 真实等待/失败即使 Operation 仍在收尾也保持红色。产品待回复/审批不因旧成功操作变绿。
- DONE 七节点均绿；CLOSED 不冒充交付完成。当前任务优先，旧 candidate/Task 不影响当前节点。
- API execution UNKNOWN 与持久化历史保留，执行器细节放工程区；不增加权限、Schema 或诊断。

## 存量与回滚

纯前端派生无需改库，历史 bytes/hash 与审批不改变。更新前端资产刷新页面即可；回滚本次前端
资产并刷新，不需要重建需求或重复批准。
