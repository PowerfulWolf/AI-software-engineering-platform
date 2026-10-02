# 后台轮询增量更新

## 目标与验收

5 秒轮询只更新变化的页面数据区域，保留未变化区域的 DOM、展开状态、帮助弹层、焦点、
选择范围、输入草稿、文档及调用诊断正文、滚动位置。同一需求更新下一步时保留已有文档。
项目/选中实体或精确 checkpoint 改变时重新校验操作，不能保留过时授权。
设置、状态、知识、团队、需求页面均按相关数据更新；导航和明确编辑仍遵守现有渲染约束。

## 范围与验证

允许修改 team_view/app.js、受影响前端测试、docs/development/ui-interactions.md 和 Trellis。
仅增量运行 polling-state、interactions、async-boundaries、settings-layout 及相关轻量契约测试。
无 API/Schema/数据库变化。保存当前其他 Python/MySQL 工作。单 Agent，在当前目录实施。

## 回滚与存量处置

回滚前端改动并刷新浏览器即可；不修改历史 Task、审批、Operation 或知识资产。
