# Design

使用既有原交付 Supervisor、Task 锁、historical claim、冻结工程策略和 queue fence，不再建立旁路执行器。HANDLE 与只观察的 INSPECT、人工 RESOLVE 分离。Manager 对平台服务提交 exact 等待身份，服务输出 handling 状态、调查、允许决定、用户动作、复查条件和 digest。

Resolution 可选择 engineering_operator_decision（真实工程主体）或 organization_engineering_policy（完整 exact EngineeringAdmission）。新 delivery_wait_resolution capability 仅冻结到新 Task；旧任务不追溯扩权。未知执行不退款、不推断停止、不跳过 QA/Review。

事实收集优先恢复已封存的 final route result。后续补齐仅使用原 claimed start inventory、runner owned stop 与 typed cause/output presence，先核验原历史 authority、scope/source/权限和完整 inventory，再封存 interruption receipt。只有原start或旧无ledger保持平台故障处理记录，不能假造 TIMEOUT。

Good: exact safe proof + frozen capability → automatic resolution + 原Supervisor一次；Base:旧无新cap但完整proof→明确一次human方案决定；Bad:未知stop→保留等待和具体报告，绝不接受用户stop布尔值。
