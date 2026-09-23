# 增量验证

- `node --check src/ai_software_engineer/team_view/app.js`：通过。
- `node --test tests/team_view/ui.test.cjs`：6/6 通过；验证精简当前摘要后仍可按完整路由选项选择、增删和排序备用模型。
- `NODE_PATH=<Codex bundled node_modules> node --test tests/team_view/browser/settings-layout.test.cjs`：2/2 通过；覆盖 1440/768/390px 布局、等宽按钮、禁用态及窄屏下添加备用模型。Chrome 需在受限沙箱外启动。
- 桌面和 390px 测试截图已人工检查；没有长文本截断主模型、漂浮的操作链接或横向溢出。
- `git diff --check`：通过。按用户要求未运行全量测试。

已知风险：未做其他浏览器的人工视觉验收。存量数据处置：本次不修改 Schema、配置、Requirement、Task、Operation、审批或数据库事实，无需迁移。回滚方式：恢复本次前端/测试/规范提交并刷新页面。
