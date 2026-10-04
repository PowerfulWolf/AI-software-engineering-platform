# 实现与验证

移除两个 Delivery 知识入口的隐含 120 秒限制；新增精确 pre-code knowledge restart、source/target base 分离与 current target 执行入口。保留旧 Task/事件/调用、原批准范围和独立 QA/Reviewer。

回归暴露的第二个问题：target 更新后，原 require_restart_dispatch 把 source_base 误当 target_base；接着旧 frozen backend 无法执行新 preparation。分别修复精确基线契约和同一 catalog 的 backend 重建，真实 Git/MySQL fixture 可完成父需求。

验证均为增量：知识窗口/恢复 proof/本地超时/中文显示；隔离 MySQL 的 7 个初始恢复案例（含 crash、Coder 失败和 QA 失败）通过；独立的原生入口/Schema/知识测试 152 通过；Node DOM 6 通过；生产 10 文件 mypy 通过。最终质量门结果见提交前检查。

最终增量：`test_restart_contracts.py`、`test_execution_retry_budget.py`、`test_blocker_text.py` 和 `tests/web_console/test_manager.py` 共 116 通过；新版 Schema/SQL 行身份检查后，当前基线知识重启和 worktree 保留场景 2 通过。Ruff/diff 通过，13 个变更生产/测试文件在 `mypy --follow-imports=silent` 下通过。默认跟随导入时存量 `tests/recovery/test_resume.py` 有 13 个既有类型错误，未改该文件；生产 10 文件标准 mypy 独立通过。未运行全量测试。

## 存量数据处置

父需求 delivery_multi_74df2af872dd99c7b3369341c6a663c707aebb97，原 Task task_da6d0347b14c9ab6d9fd1a6bf0b74dbf；保留其 BLOCKED/revision3/attempt1 和 sealed 知识超时。部署前确认无 active Operation，同步 target main、重启；通过正式 Continue 生成绑定修复提交的当前计划，代用户精确批准，再经原生角色交付。没有 SQL update 或历史改写。离线 fake 通过不代表真实需求 QA/Review 已完成。

回滚：消费新 kind 前可撤销提交并空闲重启；之后保留兼容读取器、优先前向修复，不删除计划/授权或重置终态。浏览器验收不可用，已做 API/DOM 增量验证，不声称视觉验收完成。
