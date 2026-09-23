# Agent 模型分配详情视觉优化

目标：修正展开详情中主模型文字过长、宽度松散、备用模型操作像漂浮链接的问题。只改设置页呈现，不改变路由选择、排序、移除、保存或密钥语义。

验收：主模型选中项显示精简模型名，完整路由信息仍在选项中并在当前项旁可见；备用模型以编号、模型名、路由元信息和明确的等宽操作按钮展示；添加入口与主模型共用容器边界。桌面及 390px 窄屏无横向溢出，键盘/禁用态可用；增量测试覆盖选择、排序、移除和布局。

允许路径：`src/ai_software_engineer/team_view/app.js`、`style.css`、`tests/team_view/ui.test.cjs`、`tests/team_view/browser/settings-layout.test.cjs`、本任务和 `.trellis/spec/core/web-console.md`。不改 API、Schema 或数据。回滚点：恢复本次 UI/测试/规范提交；无需存量迁移。
