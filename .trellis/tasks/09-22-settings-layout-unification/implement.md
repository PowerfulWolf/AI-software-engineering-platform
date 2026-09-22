# 实现清单

- [x] 统一 Settings 页面头、metadata、Section 和字段行结构。
- [x] 基础配置改为平台身份、运行环境、执行与重试策略三个 Section。
- [x] 保留并澄清 `live_model_execution` 安全开关。
- [x] MySQL 改为连接配置、连接验证两个对齐 Section。
- [x] 模型目录改为紧凑摘要/展开编辑。
- [x] Agent 模型分配改为角色摘要/展开编辑并对齐 fallback 操作列。
- [x] 补充响应式样式与焦点/disabled 状态。
- [x] 同步 `.trellis/spec/core/web-console.md`。
- [x] 只运行设置页增量测试并记录结果。

允许修改：`src/ai_software_engineer/team_view/{app.js,style.css}`、`tests/team_view/ui.test.cjs`、`tests/team_view/browser/{fixture,settings-layout}.test.cjs`、`.trellis/spec/core/web-console.md` 及本任务目录。

回滚点：提交 `6ec25b1`。本任务不改变配置或数据格式，回滚前端与测试即可；无需存量数据迁移。
