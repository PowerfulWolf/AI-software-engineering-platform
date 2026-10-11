# Contract
NativeRecoveryEntry已批准execute路径与ProductionProjectBackend.run_delivery使用相同等待转换。
恢复审批授权不被重新签署、不重复运行副作用；only DeliveryQueuePending转typed pending。

| Case | Outcome |
| --- | --- |
| 恢复执行等待 | 明确具体等待，不泛化为Manager未知异常 |
| 恢复成功 | 既有交接与独立QA/Review保持 |
| 未知/权限异常 | 保持原拒绝边界 |
