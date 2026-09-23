# 设置页按需说明与对齐

目标：基础配置、MySQL、模型路由三页的解释性小字不再占用字段高度；字段标签右上方显示可点击的信息标记，点击后查看原有完整说明。包括区块、页面级解释，三页保持一致。

验收：两列模型路由的标签/控件同行对齐；Agent 模型分配详情的主模型输入、备用模型身份和添加备用模型选择器共用内容列基线；说明可键盘打开、关闭，窄屏不溢出且不被卡片裁切；表单错误、连接测试结果、密钥已保存占位符和重启状态仍直接可见；不改变配置值、保存协议或密钥回显语义。仅运行相关 DOM/浏览器增量测试。

允许路径：`src/ai_software_engineer/team_view/app.js`、`style.css`、`tests/team_view/ui.test.cjs`、`tests/team_view/browser/settings-layout.test.cjs`、本任务和 `.trellis/spec/core/web-console.md`。回滚点：恢复这些前端/测试/文档改动；无需数据迁移。
