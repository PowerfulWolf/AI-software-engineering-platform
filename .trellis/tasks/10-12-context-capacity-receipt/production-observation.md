# 2026-10-12 生产维护与原 K1 恢复观察

## 已完成维护

原服务 PID 4722，全局 operation-summaries `active_complete=true, active=[]`。
使用有效 ASE_CONFIG 经 service stop 完成安全记录保存、执行器/索引结束与退出，无 kill。
主维护 main fast-forward 到 `9cccb5b5a0eff3b1c3dff6fc0cc5c5210b9fa550`、`uv sync --locked`
成功、origin/main 推送成功。目标 checkout（ai-workspace 下同名仓库）原 clean，fetch/ff-only
同步到同 commit。受控 service start 成功，新 PID 43582，status 可接收新操作。

独立性能回归最终为 71 passed。部署后的单次完整 Project GET 为 12.84 s / 2802572 bytes，
对比旧版本单次 15.58 s 只能证明当前仍慢，不能作为稳定提升比例或无内存泄漏证明。
2 Requests、25 Tasks；aggregate document/history payload：Request 文档 231473 bytes/7项，
Task 文档 1513328/125项，timeline 68620/36项，execution_history 873359/518项。
后续 summary/detail 优化须保留完整历史与精确授权，详见独立性能任务 research.md。

## 原需求受控恢复

父 Requirement `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`；native child
`delivery_dc5cf0aee44e5ffe0cb600557204e0d0`。无新同名 Requirement。

通过公开 POST /api/v1/operations 提交 ContinueDeliveryIntent：

- proposal Operation `operation_e481c73f2775366f6fe29257ef8e79df`，SUCCEEDED。
- 原父 checkpoint `f1fe8e58f7d73f17b9dbd9fa35450000fb710f43c85450b3a19c2097467d69aa`。
- 精确方案 `45588301d1b35b02f44762650b6195e4d4a4902b15b128e5f90bc418b4661367`。
- 方案从 trusted open_recovery_plan 完整读取并通过 integrity；capacity source 无失败 Run，
  input_mode=coder_reapply，target=9cccb5b；有完整 target_authorization，权限不允许 merge。
- 完整旧补丁再次核验 604438 bytes，SHA
  `c085ce5563e49e446c861eb4771cc3634af2f8ad0ebb27181175d9cbf80211f5`；未截断或手工适配。
- 当前页面审批明确解释未调用、旧补丁、目标基线、继续同一需求、独立 QA/Review。
- 依用户已有代理审批授权提交 exact approved_plan_sha256，操作
  `operation_4e6715d6917b2d10050d5203c6f24996` 已 RUNNING。

本记录写入时尚未观察到新模型调用，准备/审批/Operation 运行不等于实际交付完成。
旧 terminal Task 与事件不改写，没有直接 SQL 修改、历史清理、业务补丁手工修冲突或自动 merge。
