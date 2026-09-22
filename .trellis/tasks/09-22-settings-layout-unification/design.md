# 平台设置统一布局设计

## 决策

采用已评审的“分组表单行”方案。基础配置、MySQL 和模型路由共享同一页面头、配置 metadata、Section header、`200px + 24px + flexible` 内容网格及 sticky 保存栏。Section 标题和字段标签共用左侧基线，Section 说明、控件、验证动作与说明 footer 共用右侧基线；窄屏按同一信息顺序堆叠。

模型目录和 Agent 分配是同级 Section。模型目录使用摘要行加按需展开编辑；Agent 分配使用角色摘要行加按需展开主模型与备用顺序。备用模型行固定为“位置 / 模型 / 操作”列，三个操作槽位等宽，不能由模型名称或禁用状态推动位置。

`live_model_execution` 是已有的后端安全闸门，必须保留。显示名称改为“允许调用真实模型”，说明关闭后拒绝模型任务且不会切换 fake Agent；字段、默认值、保存与重启契约不变。

## 边界

- 不修改 Settings API、ProductionConfig、Schema、secret store 或 restart lifecycle。
- 不修改模型选择、fallback 顺序、启用路由、MySQL 测试或原子保存行为。
- disclosure 只改变浏览器显示密度；所有控件仍绑定同一 `settingsDraft`。
- 页面切换继续保留同一草稿；所有密码输入继续 write-only。
- 实现只涉及 `team_view/app.js`、`style.css`、设置页浏览器/DOM 测试及相关 Trellis 记录。

## 验证

- 真实浏览器在 1440、768、390px 检查三页无横向溢出。
- 基础配置验证三个 Section、统一左右基线和真实模型开关准确文案。
- MySQL 验证两个 Section、环境变量只读展示、验证动作/footer 与控件列对齐。
- 模型路由验证两个 Section、紧凑 disclosure、七个 Agent 行及备用操作列对齐。
- 运行 `tests/team_view/browser/settings-layout.test.cjs` 与受影响的 `tests/team_view/ui.test.cjs`，不运行全量测试。
