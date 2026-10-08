# Goal

需求详情章节导航在桌面内部滚动时与容器顶部连接，背景覆盖顶部和两侧，避免上方旧内容
从内边距空隙透出而显得悬空。保留按钮原有对齐、间距和焦点空间。

# Scope / allowed paths

仅修改 `src/ai_software_engineer/team_view/style.css` 与相关 Trellis 规范/本任务记录。
不改变导航 DOM、章节内容、交付操作、状态或生产数据；任务详情现有工具栏无需修改。

# Acceptance

- 1440px 桌面内滚动，导航背景贴合详情容器内边框，旧内容不从顶部/两侧露出。
- 1024px/390px 随页面滚动时，仍 top:0，按钮和章节跳转目标完整可见，无横向溢出。
- 共用详情滚动内边距变量，不新增脱离容器布局的固定偏移。
- 增量浏览器 requirement-detail 与 task-detail-reading 通过；隔离截图前后比对。

# Verification / rollback

使用现有 Chrome fixtures、几何测量和截图，不新增低影响样式的单元测试，不跑全量测试。
生产 Console 启动时缓存前端资产，在服务空闲时由用户重启服务后刷新生效；无需改库或
恢复需求。回滚 CSS 后同样需重新加载服务资产。
