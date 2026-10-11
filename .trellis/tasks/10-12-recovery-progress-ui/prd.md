# 恢复准备摘要、命令结果与控制可用性分离

## 问题与目标

有界操作摘要上线后，需求操作记录不再复用当前节点派生进展，丢失恢复准备与最近已保存的准备记录。
摘要历史把 SUCCEEDED 命令显示为蓝色“执行成功”，即使当次交付实际 BLOCKED。
另外，可信精确恢复记录已读取、Team 读取正常，但服务暂不可接收控制或完整详情尚未就绪时，
当前节点退回原 STOPPED“已阻塞”。展示和控制资格不应混为一谈。

## 范围、验收与允许路径

- 摘要模式通过同一 currentOperationProgress/recordedOperationOutcome 展示当前进展和当次封存结果。
  当前进展必须进入 keyed row signature；完整历史结果不能附上最新需求阶段。
- SUCCEEDED 命令统一中性“命令已完成”，封存 BLOCKED/WAITING/DONE 由独立标题说明，不能推断验收。
- 已读取完整且精确绑定的 RUNNING 恢复及已成功准备的来源，独立支撑“平台正在处理恢复”阅读。
  consoleDeliveryReady=false 或 full-detail gate 未就绪不改写其事实，也不恢复任何控制资格。
- 新失败/新等待/过期/真实 Coder、QA、Reviewer claim 保持原优先级；UNKNOWN、摘要而非完整来源、
  stale/unavailable Operation、外 Team/Project、切换及不匹配 checkpoint/plan 不生成恢复事实。
- 当前 Project/Requirement 摘要页同 ID 的 status/sequence/digest 不一致时拒绝只读恢复判定，
  items/active 同页冲突同样拒绝；一致重读后恢复阅读，不改共享读取器、审批或 POST gate。
  active 一致性必须在可控与不可控展示分支共同生效；普通 Continue 不增加 approved-plan 字段要求。
  已缓存 Team-wide 页参与既有读取器，也必须纳入同 ID 一致性检查；逐项校验精确 Project。
- 仅改 app.js、新精确 Node fixture、console-operation-summary-ui.md 和本任务目录；不改 Schema、SQL、
  API、审批/freshness gate、生产/注册 checkout、服务或模型，不跑全量测试。

## 验证命令与回滚点

基线 50bc91c；先新增实际 requestOperationHistory/公开读取事件 fixture 得到 3 类红例，修后跑新文件及
相关 operation-summary-reading/operation-progress/preparation-progress/delivery-status 增量 Node 测试。
独立 reviewer 复核门禁分离与负例后提交。回滚此次前端和测试/spec 提交，保留后台有界摘要接口。

## 存量数据处置

只读派生错误，无需改库或改写 Task/Operation/approval/journal/失败/停止/预算历史。空闲受控部署后刷新原需求
重新读取；不新建需求、不重复批准或启动执行。上线仍由根任务在生产真实空闲时完成。
