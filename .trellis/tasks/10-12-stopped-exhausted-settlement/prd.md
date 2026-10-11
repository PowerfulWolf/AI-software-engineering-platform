# 已停止失败的真实额度耗尽等待收尾

目标：修正旧版本将非临时失败误放入临时故障等待、普通执行额度已耗尽却无法进入原需求恢复的流程。INSPECT 只读；公开 HANDLE 严格核验原执行、真实停止与完整现场后，原子追加合法 BLOCKED 事件并关闭唯一旧工作项。保留原需求、草稿、失败、attempt 和预算；继续必须另走既有精确恢复批准。

验收：原记录/历史前缀不变；无模型调用、claim、退款或verdict；缺停止、活进程、外来领取、现场变化、候选或未耗尽拒绝；SQL前后重入只产生一条事件；中文结果说明下一步。只跑增量测试。

范围：domain/stopped_budget_settlement.py、domain/delivery_resolution.py、manager/stopped_budget_settlement.py、manager/delivery_wait.py、manager/wait_fact_collection.py、manager/production_host.py、work_queue/execution_store.py、相关Schema/测试/spec。

回滚：部署前恢复源码即可；发布新记录后保留增量reader，不删除任何草稿、审计记录或恢复批准。
