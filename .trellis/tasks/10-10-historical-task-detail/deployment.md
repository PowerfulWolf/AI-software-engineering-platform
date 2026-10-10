# 部署待办（2026-10-10）

历史详情与当前需求的展示修复已通过增量及独立审查。生产 PID 21248 在启动时冻结
前端资产，当前仍提供已提交 4bf596d 的资源；源文件更改不代表当前页面已加载修复。

原 K1 的 Operation `operation_7b779aaf66c87cc8b486eba3b7ec378a` 正在主 Coder 执行。
保留该调用，待公开 Operation 完成并确认当前服务所有执行/写操作排空后，使用现有
受控 service restart 加载已提交代码；随后比较 /app.js 和 /style.css HTTP bytes 与
已提交源码 SHA，并核验 Console contract/readiness 和原 K1 的最新状态。

不得以资源部署替代原 K1 的独立 QA/Review，不操作旧历史，不重复需求审批。
浏览器 CUA 认证不可用，真实布局、焦点、点击和响应式仍未验收。
