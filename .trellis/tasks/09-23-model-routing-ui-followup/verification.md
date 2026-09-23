# 增量验证

- `node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs tests/team_view/knowledge-gap.test.cjs`：41/41 通过；覆盖 Status Responses 类型、历史未知连接方式和全局 render 的其他交互。
- `NODE_PATH=<Codex bundled node_modules> node --test tests/team_view/browser/settings-layout.test.cjs`：5/5 通过；Chrome 在受限沙箱外执行，覆盖 Agent 弹层/主模型垂直对齐、候选用尽后的新路由到备用模型流程、模型目录折叠，以及 1440/768/390px 既有布局。
- `node --check`（受影响 JS）、`git diff --check`：通过。按用户要求未运行全量测试。

已知风险：没有在用户真实配置上提交测试性 PUT，也没有对其他浏览器做人工视觉验收；本次是静态 UI/展示逻辑更新，刷新页面即可加载。存量数据处置：未修改 Settings API、`ProductionConfig`、密钥、Requirement、Task、Operation 或数据库事实，无需迁移。现有 Agent 路由与备用顺序不变。回滚方式：反向提交本次提交并刷新浏览器；无需重启服务或回滚配置。
