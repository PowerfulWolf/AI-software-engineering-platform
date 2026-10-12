# 增量验证与存量处置

真实RED：新增 `test_automatic_wait_authority_isolates_tasks_without_overwriting_legacy_scope`
驱动真实 DeliveryWaitService.handle → _resolve → FileRecoveryStore.initialize，旧固定目录
完整scope属于anotherTask。修复前 **1 FAILED / 5.57s**，精确异常
RecoveryConflict: recovery record already has different content，匹配生产失败。

变更后 **8 PASS / 29.72s**：上述节点、shared admission已写但decision未发布的原序号恢复、
当前scoped root foreign/symlink/corrupt（三例），既有冻结policy幂等、decision落盘queue消费
后的恢复、clock改变后partial publication。新的五例与三例已有相关回归一起执行。

命令使用绝对本worktree `PYTHONPATH=.../ase-task-wait-authority/src` 和项目共享
`.venv/bin/python -m pytest`，精确selectors位于tests/manager/test_delivery_wait.py。
Ruff check/format check、strict mypy 两文件、git diff --check全部通过。
独立审查source/tests/spec/task PASS，不重复已过增量；无全量、生产数据库或模型测试。

原生产Task task_recovery_45588301d1b35b02f44762650b6195e4，已成功基线更新733f0ada...
并明确继续的Operation operation_9d60ce47bda23ddc9dd58813b43ad721于07:21:50Z失败。
已知scope冲突：旧0d73eca60377373cfb375905afa367c22ab50f42a9cf15804e9f5751d6591412、
当前7ee97ec648a5a77fb5714d6e7193696d927fc7c3ba1a04c78c53f232bfa12866，仅delivery_id不同。
旧scope/admission、原Task/草稿/批准/预算保持，无需SQL或文件迁移。

存量恢复：在全局operation idle时受控stop→更新已审版本→start；fresh读取原Task等待。
通过原公开HANDLE_DELIVERY_WAIT重新核验验证前提，在原冻结授权预算内保存决定并继续。
原FAILED Operation不得改成成功；若当前前提并非READY仍保持对应等待，不通过本修复假定停止
或模型成功。后续角色依然必须独立QA/Review。

回滚点f91f33a。开始写入新scoped目录后保留兼容写侧和全部新历史，优先forward fix。
