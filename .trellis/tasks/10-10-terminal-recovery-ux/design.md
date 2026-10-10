# 契约与验证

`ConsoleApprovalRequest.technical_facts: tuple[NonEmptyStr, ...] = ()`，空值从 wire/hash 省略。
`recoveryApprovalBox(request, approval)` 直接渲染 `facts` 与批准按钮，非空 technical_facts 使用
已有 `engineeringDetails` 的独立展开区，textContent 安全渲染并由现有 approvalSignature 绑定。

Good：当前精确恢复方案包含完整现场证明，用户看到保留进度/异常环境隔离/独立验收说明。
Base：旧方案没有新增字段，原事实照常显示，摘要完全一致。
Bad：把未知执行说成停止、把旧缓存审批当当前授权、把技术摘要要求作为产品需填写的内容。

增量：product-execution.test.cjs、engineering-wait.test.cjs、test_manager.py、scope/schema contract。
不改变审批的执行权、Task 状态、角色 verdict 或业务范围。

## 完整现场的审批绑定

`RecoveryPlan.workspace_snapshot: RecoveryWorkspaceSnapshot | None`。None从wire/hash省略，
原计划摘要不变。非空必须绑定源Task/revision/SHA、run/context、Team/Repository/native
Requirement/dispatch、worktree/source/effective base与完整capture SHA，并先校验自身摘要。
现代失败现场必须由正式helper提供；旧计划缺该证明时当前facts复核拒绝，用户重新准备方案。

proposal在封存计划前观察实际停止、可信原调用和完整inventory；current facts在批准及
dispatch fence内重新观察，变化则拒绝原计划。helper不再获取global authority fence，
防止恢复提交中的锁重入；现代已接纳progress按既有精确provenance契约兼容。

UI只在计划包含可信snapshot时显示“原执行已停止”和“完整清单已核验”；excluded_paths
非空时明确解释误建环境只在原现场保留、不进入恢复工作区、不授予写权限。
snapshot摘要/真实时间/清单规模归入技术信息，不要求用户输入hash或操作维护进程。
