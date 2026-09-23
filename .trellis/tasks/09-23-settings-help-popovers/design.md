# 设计

复用单一 `settingsHelp` 组件：按钮使用可访问名称、`aria-expanded`/`aria-controls`，说明使用纯文本和原生 Popover top layer。Popover 贴近触发按钮并受视口边界约束；浏览器原生 light-dismiss/Escape 关闭。字段、模块、页面标题复用同一交互；重要状态和反馈不折叠。模型路由字段改为固定标签行和控件行，帮助按钮不嵌入 `label`，避免嵌套交互控件。区块尾部纯解释并入区块帮助内容。Agent 模型分配展开详情改为 76px 标签/位置列、10px 列间距，主模型与备用模型内容从同一基线开始。
