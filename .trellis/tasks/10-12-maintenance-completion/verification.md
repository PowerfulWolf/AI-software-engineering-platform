# 维护完成入口验证

实现基线 bf3f3a8，隔离分支 codex/maintenance-completion-20261012。

## 验证命令与结果

所有 Python 检查使用主仓 .venv/bin/python，工作目录为本任务隔离 worktree，PYTHONPATH=src。

- `python -m pytest tests/web_console/test_maintenance_completion.py tests/web_console/test_maintenance_queue.py tests/web_console/test_maintenance_completion_script.py tests/web_console/test_fault_retirement.py tests/web_console/test_inspection_console.py tests/web_console/test_inspection_fault_boundary.py tests/web_console/test_service_lifecycle.py -q`：100 passed；2 条现有依赖弃用警告。
- 原服务脚本五个关键回归：5 passed。
- `NODE_PATH=<bundled node_modules> node --test tests/team_view/browser/inspection-console.test.cjs tests/team_view/team-summary-reading.test.cjs`：30 passed。真实 Chrome fixture 检查维护入口可读、展开状态保留、没有交付 POST。
- 受影响生产 Python 文件增量 mypy：无错误。
- 受影响 Python 的 Ruff lint、格式检查和 `git diff --check`：通过。Schema parity 包含在上述 pytest 中。
- Spec 与 Standards 两轴独立复审：未发现剩余明确问题。原始回执 root anchor 发布中断后的链恢复、SQL 完整结构及索引/payload 一致性问题均已修复并有负向测试。
- 未运行全量测试。

## 真实环境只读核验

新 observer 只读核验生产队列：342 条 Console Operation、97 个 WorkItem、112 条 claim，0 未结束操作、0 可运行/重试工作、0 ACTIVE claim；1 个 WAITING 工作保持。检查覆盖选定数据库全部队列，不构造 TeamHost，不初始化或迁移表，不执行 SQL 写入。部署前服务 PID 57391、Console mode=inspection、supported_actions=[]。这些事实不代表 K1 开发、QA、Review 通过；实际确认解除维护及首次普通服务验收留给用户。

## 存量数据处置

本任务不修改 K1 的 Task、WorkItem、Operation、审批、verdict 或开发草稿。不调用需求处理/恢复接口、不解除维护、不改生产 SQL。原故障 marker、退休档案、完整日志及 UNKNOWN 原执行结果保留。新计划、回执、首次普通 admission 只有在用户执行新本机入口时追加；旧档案不删除或改写。
用户路径：页面顶部展开“完成维护并恢复普通模式” → 运行 prepare-maintenance-completion（受控停止并核验） → 阅读方案 → 用精确 record_sha256 执行 complete-maintenance ... --confirm-restore-normal → 刷新确认普通模式。服务恢复与需求继续独立。

## 风险与回滚

原故障日志约 10 GB，完整字节哈希校验可能需要等待。队列、配置或停止事实漂移将保守拒绝；本机替换锁不隔离其他 CLI/Worker 对共享数据库的写入，应先停止其他写入入口。未实际退出生产维护模式，也未验收 K1 完整交付。回滚点 bf3f3a8；保留所有维护记录和原故障归档，可显式 ASE_CONSOLE_MODE=inspection 经受控脚本启动。完成普通 admission 后不应直接使用不理解新回执的旧普通服务；不得删除 marker、伪造 READY、重置队列或强制终止进程绕过检查。
