# 上游阶段执行时间扩容

## 目标

Product、Designer、Planner 的完整产物调用达到本地执行时限时，与可识别的模型服务故障分流；前者按有界容量增长重试，后者保留既有临时故障/fallback 语义。Manager 当前为确定性编排，不引入虚构的模型时限。

## 范围与验收

- 本地 Codex CLI 看门狗超时不切备用路由、不扣临时故障额度；按阶段在联合 checkpoint 持久化独立计数。
- 下一次同阶段调用使用 600、1200、2400 秒的有界时限；第三次仍触顶后不再发起必然失败的调用。
- HTTP 504、连接异常及 Responses socket timeout 仍按临时故障处理；非法输出不退款。
- 保留审批、历史、模型诊断与精确恢复边界；旧 checkpoint 可读，不修改生产数据。
- 当前阻塞与界面阶段问题独立排查，不能以超时修复掩盖现有存量事实。

## 允许路径与验证

允许修改 agents/structured.py、multi_directory/service.py 与 budget.py、team_view 的读侧及关联增量测试、相应 Schema 与规范。仅运行受影响测试、Ruff 与类型检查；不跑全量测试。

## 回滚点

回滚本任务提交即可恢复旧调用策略。新 checkpoint 的超时计数作为历史事实保留；回滚代码不得删除或改写 journal。
