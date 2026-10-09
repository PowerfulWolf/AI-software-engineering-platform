# 分工

根 Agent：历史 key 兼容、真实存量校验、任务/spec和整体验证。
team_read_performance：reader/退休历史重复读取和相关Python测试。
console_refresh_reliability：app.js 刷新独立发布、失败保留及相关JS/browser测试。
history_failure_contract：只读确定旧key与规范边界。
