# 原需求恢复审批的用户交互

## 目标与范围

用户需要理解原需求为何暂停、哪些开发进度会保留、异常环境如何处理，以及批准后如何继续。
Console 的恢复审批应直接展示这些工程决定；Task ID、基线 SHA 和分支等定位信息归入可展开的
排障信息。精确审批门禁、当前绑定复核和完整执行历史保持不变。

## 验收

- 恢复审批标题描述保留开发进度并继续原需求，明确不是新建同名需求。
- 已验证的停止、完整现场和异常环境隔离按可信 workspace snapshot 展示；没有证明不显示已核验。
- 决策事实为常规正文，源码/Task/摘要作为可展开排障信息；批准入口始终直接可见。
- 旧审批字段缺省仍可读，旧 Operation canonical bytes/digest 不变。
- 不可读、跨 Project、旧 checkpoint 或 detached callback 保持原拒绝行为。
- Node DOM、Python Console 契约与 Schema 增量通过；浏览器认证不可用时不宣称视觉验收。

## 允许路径、验证与回滚

`web_console/models.py`、`manager.py`、`team_view/app.js`，对应 tests、Console Schema 与文档。
只跑增量测试和限定 lint/typecheck。新增可选 `technical_facts` 空值不进入旧序列化/摘要。
无数据库迁移，无历史记录改写；存量从当前精确计划重新读取。新记录发布后回滚必须保留可选字段读兼容。
