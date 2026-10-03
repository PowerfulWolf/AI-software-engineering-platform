# 实现计划

1. 先写 projection 与 Team View 增量 fixture：多轮报告、历史 successor、空 findings、超过八条记录。
2. 在 projection 中增加报告摘要和 lineage details；在 Reader 中保留 details 并聚合同一 delivery 的历史 Task。
3. 扩展 TaskView/Team snapshot schema，更新浏览器任务详情，显示当前/历史轮、finding 和 Coder 输入反馈。
4. 运行 `pytest` 的 projection/team_view 相关文件、Node team_view UI 套件与 Ruff/mypy 相关模块；不运行全量测试。
5. 更新 Live Team View 规范，完成检查后提交并推送平台修复。
