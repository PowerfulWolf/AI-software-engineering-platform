# 实施

1. 已完成真实最新 Operation/服务版本与 OS 占用复现，建立精确失败原因。
2. 先新增稳定 bundle 工具链的回归测试，再实现受限归属核验。
3. 复核负例、覆盖完整性、identity/reparent 漂移、真实 exec/e 与 public Host 恢复组合。
4. 真实原 K1 只读验证；独立代码/规范审查；完成规范、存量说明，提交推送。

已完成：scanner 先 red 再 green，最终178用例；公开Host两场景通过，额外legacy/Console/Schema
56用例通过。独立审查发现全链fake bundle来源问题后已固定安装根并添加负例；最终审查无
剩余阻断问题。最终真实原K1调查无blocker且完整工作区/index/HEAD/branch未变。

实现 agent 仅拥有 scanner 与 scanner 测试；root 拥有任务/规范，调查 agent 拥有 verification。
本任务不运行全量测试，不操作生产需求/审批/重启，不撤销其他维护者改动。
