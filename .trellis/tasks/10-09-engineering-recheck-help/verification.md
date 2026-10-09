# 验证与交付

- `node --check src/ai_software_engineer/team_view/app.js`：通过。
- `node --test tests/team_view/engineering-wait.test.cjs`：31 项通过。
- `NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules ASE_UI_SCREENSHOT_DIR=/private/tmp/ase-recheck-help.2xSZzt node --test tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/legacy-rescue.test.cjs`：13 项通过。使用隔离 Chrome 与拦截 API，无生产操作。
- `git diff --check`：通过。只运行上述增量测试，未执行全量测试。
- 浏览器验证点击、Enter 打开、Escape/关闭按钮、三点提示、无关标题轮询时同一弹层保留、说明不触发 POST、1440/1024/390 px 按钮角标位置与提示无溢出。已查看桌面与手机截图。
- 复用 `settingsHelp`，仅本角标使用保留换行的纯文本；未改变共享帮助交互。工程等待动作签名包含派生的恢复入口存在性，避免保留过时说明。
- 使用 Trellis finish-work 核对代码、规范、浏览器验证及提交边界。本次无 API、Schema、数据库或权限变更。

## 存量数据处置与回滚

无需改库或重启，浏览器刷新一次加载新资产即可。现有需求、审批、执行记录保持原样。
回滚本任务提交并刷新浏览器恢复旧展示。已知限制：仅优化当前工程等待复查按钮的使用说明，调查条目中的具体下一步和复查条件仍可直接阅读。
