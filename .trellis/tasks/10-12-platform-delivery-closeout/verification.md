# 分阶段验证

## 日志启动依赖与维护完成入口

先运行新回归 `pytest tests/web_console/test_fault_retirement.py -k startup_authority -q`：3 failed，明确复现日志缺失、变化和被禁止读取时启动失败。
修复后 `pytest tests/web_console/test_fault_retirement.py tests/web_console/test_maintenance_completion.py tests/web_console/test_maintenance_completion_script.py tests/web_console/test_inspection_fault_boundary.py -q`：71 passed，2条已有依赖弃用警告，58.29秒。涵盖真实故障退休、已删除/变更日志启动、日志清理确认/固定路径/权限/真实writer/幂等/发布失败重试、维护完成与normal admission及损坏控制记录拒绝。
新增Schema生成与parity一致；日志相关4文件mypy通过；Ruff检查/格式及shell语法通过。两轴独立复审无阻塞问题，旧规范中log变更阻止startup的表述已同步。维护完成入口在前一任务已有100项Python+30项前端+5项服务脚本增量验证。未跑全量。

## 历史分支审计

固定基线bf3f3a8，完整清单见branch-inventory.json。祖先分支已合入；patch-equivalent分支经git cherry核对。4个patch-ID不相同实现由独立审查逐文件增删行核对：f6e8c94→f6fd6e4、c97c077→39db99a、edaac21→d4fdf21、01b765a→ec55d53，均无丢失实现；差异来自上下文、空行、额外索引或已存在测试验证。beaa43a/e0cd6d5的32行历史部署/审批记录未整合，需补入。未提交恢复fixture仍待验收；旧completed-output草稿已由主干正式实现与更强后续验证覆盖；service_maintenance旧prototype已被fault_retirement+maintenance_completion替代，不作为生产代码整合。

## 存量数据处置与回滚

日志修复不更改Task、Operation、审批、verdict、队列或未知原执行结果。生产日志清理、受控服务替换、基线批准及K1进展将在实际发生后逐项追加。删除仅诊断正文不可逆；旧日志摘要和控制事实保留，当前日志不在清理范围。日志删除后不得回滚到依赖正文的旧reader；可维持inspection并前向修复。
