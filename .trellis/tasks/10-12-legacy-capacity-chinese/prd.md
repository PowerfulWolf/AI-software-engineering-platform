# 历史输入容量停止原因中文展示

线上 Request.blocker 与 Task.blocker 的精确历史文本
`Required context exceeds the configured input budget; no automatic retry.`
未进入现有中文映射，用户看到英文且不知道下一步。

仅在纯读侧将此稳定平台文本翻译为中文，说明平台需要调整输入装配，并为原需求准备保留完整
开发进度的恢复方案。不能单凭历史文本宣称旧模型未调用、额度未消耗或恢复已获批准。

允许路径：`src/ai_software_engineer/team_view/blocker_text.py`、`app.js` 中的
`humanizeBlockingText`、`tests/team_view/test_blocker_text.py`、相关规范与本任务目录。
不改其他状态展示逻辑，不重启服务，不操作需求或审批，不重写存量数据。

验收：精确英文句子在 Python 和 Node 浏览器 helper 中输出同一中文；普通
`RETRY_BUDGET_EXHAUSTED`、普通工作预算诊断、包含该句的用户引用和未知诊断保持原义。
先运行红测，再运行该测试文件、Ruff、strict mypy、Node 语法与 diff 检查，提交前独立复核。

存量数据处置：无需数据库或 journal 迁移。加载本次读侧映射后，GET Team 和浏览器对原记录
重新展示中文。此变更不授予恢复权限，也不改变原需求的安全恢复前提。

回滚点：`9cccb5b`；只回滚本次提交并刷新页面，所有 Task、Operation、Run 和审批保留。
