# 恢复执行等待结果

## Goal
已批准恢复首次执行的 DeliveryWaiting 漏出为笼统 MANAGER_FAILURE，原需求 cursor
未挂接已经生成的恢复 Task；之后该 Task 已到第 4 次执行，又被只支持首轮的旧中断入口挡住。
让恢复入口返回真实 typed pending 和中文原因，并从精确持久化等待事实接回存量原需求。

## Acceptance
- 真实恢复执行入口的 queue pending 转为内部 NativeRecoveryPending，记录实际非终态 Task
  snapshot，不重复执行后端，复用正常继续交付入口。
- 已存在原批准、sealed Task、seed、invocation、dispatch 的恢复执行，从一致只读 SQL 快照
  校验 Task 事件连续性、完整阶段链和候选提交，以及唯一当前 typed WAITING、完整身份/
  代码版本/checkpoint 和已释放领取；无 active claim，不调用会初始化 DDL 的后端 snapshot。
- 存量已批准恢复处于 IMPLEMENTING/QA/REVIEW 时均可先接回 typed wait；只有没有这种等待的
  IMPLEMENTING 任务进入旧首轮中断逻辑。显式核验 invocation 与 plan/seed 的精确 digest。
- 已验证存量等待先接回原需求，再进行独立调查/处理；不伪造异常、旧结果、停止或恢复批准。
- 未知异常不吞掉，审批/claim/原Task/dirty现场及预算不变。
- 先真实入口红回归，然后正向、负向增量测试。

## Existing data and rollback
无 SQL/schema/历史迁移。旧失败 Operation、原终态 Task 和完整恢复执行历史不重写；
加载新版本后，通过原需求公开“继续交付”校验并追加原需求 cursor，接回已有恢复 Task。
条件不齐时维持拒绝，不新建需求、重跑已消费 invocation 或通过 reader 伪装 cursor。
接回只恢复操作入口，真实后续执行仍需原 typed 等待的独立授权/处理，不能直接接纳拒绝报告。
回滚代码不改已保存执行事实；不得把错误展示修复当成旧产出已接纳。
