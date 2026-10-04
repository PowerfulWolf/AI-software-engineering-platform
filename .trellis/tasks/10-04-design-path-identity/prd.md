# 技术设计同名文件误报与拒绝诊断

## 目标与范围

新 K1 需求的联合设计和计划已经接纳，但原生 Designer 在 Task 创建前拒绝 learning_collection/ports.py 等合法新模块文件：校验以 basename 判断其他目录的已知文件身份。同时 production backend 隐去拒绝原因，只显示 DesignerOutputRejected。

仅修改技术设计路径语法检查、已知拒绝的安全中文诊断、相关增量测试和规范。完整仓库相对路径是文件身份，Profile 的语言/构建标记不是完整文件清单或“不得新增同名文件”的约束。不扩展角色权限，不改批准、候选、verdict、数据库或历史。

## 验收与验证

- 实际 DesignerService 接纳不同模块的 ports.py/models.py/store.py/audit.py 和不同目录的 contracts.md。
- 绝对、非规范、遍历、反斜线路径仍拒绝；Task/工具的 allowlist、deny、隐藏规范目录和 QA/Reviewer 权限保持。
- 已知 Designer 拒绝显示具体中文原因与异常代码；未知异常文本/secret 不泄露。
- 只运行 tests/design/test_service.py、tests/manager/test_production_backend.py 的无数据库测试及相关展示测试，Ruff/增量 mypy/diff。

## 存量数据处置与回滚

部署空闲服务后通过当前需求的正式 Continue 重试同一未完成原生 DESIGNING 阶段，保留已批准产品、联合设计/计划、失败记录及计数。无需改库或伪造 Task。角色基线必须在合法恢复/重规划边界精确绑定，不能静默改冻结源。回滚此修复提交并在空闲时重启，保留全部历史。
