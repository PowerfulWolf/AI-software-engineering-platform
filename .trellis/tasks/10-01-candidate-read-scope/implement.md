# 实现与验证

- 新 typed scope/binding 从原 Task Context 和封存 Plan/Implementation 选基线与依赖。
- 正常/独立 CLI factory 与 Manager coordinate 三处接到同一完整候选差异构造器。
- 固定对象/完整库存、Task deny、blob/source/final prompt预算、streaming Git输出；不扩Agent权限。
- CLI user JSON无损对象编码；diff原文frame绑定bytes、SHA、脱敏和包摘要。
- 回归先在真实 factory 复现全仓2MB拒绝；增量5个模块78 passed /11.05s；六个生产文件Mypy通过。
- 独立QA指出tree对象可冒充commit，已增加实际Git对象类型拒绝；Reviewer无界capture问题已改
  stdout/stderr streaming硬限并回收进程。独立QA同5模块78 passed/10.88s；Reviewer最终无剩余
  finding。其提出路径secret-like文本拒绝已补定向测试，QA旧mock和规范遗漏也已补。
  prior_visual_evidence额外1项0.97s通过（独立离线Manager claim fixture已更新）。
- 真实K1只读离线核算：旧最终131,966 tokens，新122,763；生产max128,000不变，未调用模型。
  这不是候选QA verdict；新受控receipt及Reviewer报告仍需各自最终预算检查。
- 存量恢复见规范：保留bd40ce05、终态与原失败，用新精确候选验证审批，不重跑Coder/重置预算。
