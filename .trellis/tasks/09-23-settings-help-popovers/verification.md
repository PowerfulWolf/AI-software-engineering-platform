# 增量验证

- `node --check src/ai_software_engineer/team_view/app.js`：通过。
- `node --test tests/team_view/ui.test.cjs`：6/6 通过。
- `NODE_PATH=<Codex bundled node_modules> node --test tests/team_view/browser/settings-layout.test.cjs`：2/2 通过；Chrome 需在受限沙箱外启动。覆盖三页的说明按钮、键盘开关、长说明、模型路由 API Key/图片输入同行对齐、Agent 模型分配详情的主模型/备用模型/添加选择器基线及 1440/768/390px 弹层边界。
- `git diff --check`：通过。未运行全量测试，遵守用户要求。

已知风险：未进行人工跨浏览器视觉验收；Popover 使用现代浏览器原生能力。存量数据处置：无配置 Schema、Requirement、Task、Operation、审批或数据库事实变化，无需迁移。回滚方式：恢复本次前端、测试与规范提交后重新加载页面。
