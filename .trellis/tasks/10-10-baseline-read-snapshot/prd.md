# 一次团队投影的基线绑定读快照

## 目标与依据

对同一生产数据有界读取测得完整Team快照约7秒；工程历史、待继续状态和中断历史会重复完整
核验基线绑定，最初聚合计数3次共约3.3秒。后续精确root/task计数校正为两个身份的2+1次，
不能把聚合3次都归为同Task。减少一次HTTP投影内的重复完整验证，让用户更快
看到当前事实；不把这个热点认定为未证实的小时级gate阻塞，也不缓存执行授权。

## 范围

只在team_view新增BaselineBindingSnapshot.bindings_for_task(store,task_id)，仅接受read_only。
精确root/task key，首次完整调用原store方法，成功才存tuple（包括empty）；失败不登记。
由_TaskReadSnapshot显式持有/传到engineering_history、read_pending_baseline_continuation、
_continuation_history。可选参数None保持直调完整读取。下一HTTP必须新对象完整重读，
对象不放reader实例、模块全局、ContextVar、执行service或FileExecutionBaselineStore。
现有Task/scope/receipt/authority/SQL queue/current heartbeat各调用方校验不变。

## 验收

- 实际三个调用点红capable测试：完整验证3次降1次，投影与未复用相同；实际_TaskReadSnapshot
  接线覆盖，不只测helper。
- 新snapshot观察append，历史plan/authority/capture篡改及symlink拒绝；不同root/task隔离；
  empty复用、首次失败不登记、writer store拒绝；HTTP成功/失败后引用可释放。
- 仅关联增量pytest/Ruff/format/strict Mypy；有界同真实数据前后测量，不能只报理论收益。
- 实测真实数据完整校验3→2、snapshot 6.7796→5.2838秒；同Task三个caller fixture验证3→1。

## 存量与回滚

只读优化，无Schema/SQL/历史文件迁移；原需求审批和进度保持。当前Agent执行结束或安全维护
边界后受控加载，禁止热替换。回滚本只读模块与接线，完整校验仍有效，只恢复重复成本。
