# 恢复分配前重复校验

## 事实与目标

K1恢复Operation `operation_f46b65e723e1a0c1a59f01f506c5e5e2`在12:26:41Z批准、
12:27:09Z封存Task后，于12:30:25Z完成seed、12:30:28Z开始Coder知识调用。
准备期间观察到CPU持续忙、尚无模型调用，随后自然进入IMPLEMENTING并保持有效租约。
没有证据表明死锁，不应中断活跃Coder。

独立只读Reviewer检查`recovery/task.py`、`allocation.py`、`entry.py`后发现：一次
`builder.build()`嵌套执行约10次完整native source inspection；首次正常_execute到
dispatch插入前6次build，共约60次source inspection。每次inspection再次读取两组
Task/events/dispatch、上游批准链及parent事实。恢复历史遍历带cycle guard，当前证据
支持“重复校验放大历史读取”，不支持指数递归的结论。该静态计数尚未由确定性测试证实。

目标是在保留全部审批、来源、当前事实及fence安全边界的前提下降低重复不可变输入校验。
本轮仅建任务记录，不修改执行路径，不重启运行中服务。

## 范围与验收

- 先建立确定性的读取次数回归和真实最小恢复计时，区分SQL、Git、digest与history开销。
- 设计操作内复用已校验immutable lineage；可变checkpoint、权限、HEAD、dirty capture、
  approval及owner fence仍须在关键边界重查。不得缓存跨Operation freshness结果。
- 覆盖检查期间各项事实漂移的拒绝用例；读取次数须有可复现下降证据。
- 保持旧Task/事件/审批/patch，新Task及QA/Reviewer原生执行契约不变。
- 只运行相关增量测试，由独立QA/Reviewer验收；本任务目前没有实现或通过声明。

允许路径：recovery验证、分配、封存相关模块及定向测试，本任务、delivery-recovery规范。
回滚点：`ed12f25`现有恢复行为。只回退未来代码优化，不重写生产事实。
