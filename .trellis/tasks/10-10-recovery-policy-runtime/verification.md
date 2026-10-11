# 验证记录

## 静态验证

修改恢复入口、Git seed 归一化、组合 fixture 及本任务记录。

- Ruff check：通过。
- Ruff format：通过。
- `MYPYPATH=src .venv/bin/mypy tests/manager/test_production_continuation.py`：通过。
- `pytest --collect-only`：仅收集 ordinary 和 recovery 两个参数化 case。
- `tests/git/test_seed.py`：19 passed；验证 seed 返回的 target index 没有 staged 文件。
- `tests/orchestration/test_native_continuation_v2.py tests/orchestration/test_continuation_store_v2.py`：22 passed。
- `tests/manager/test_production_continuation.py::test_public_native_entry_continues_stopped_coder_and_independently_verifies[recovery]`：1 passed，隔离 MySQL，389.60s。

## 定向组合验证

由根代理独占协调隔离 `ASE_TEST_MYSQL_DSN`，确认不等于生产 DSN 后只运行：

```sh
.venv/bin/pytest -q \
  'tests/manager/test_production_continuation.py::test_public_native_entry_continues_stopped_coder_and_independently_verifies[recovery]'
```

运行结果由根代理回传后记录。实现子代理不自行运行 MySQL，也未运行全量测试。

## 被验证的真实边界

1. 原 Task 经 Configured 工厂装配 NativeCoderContinuation，真实受控子进程写入草稿并以
   auth failure 退出，原 claim、capture-start 和真实 process-stop 完整保存。
2. 主 checkout 创建独立平台修复提交后，经正式 recovery propose 生成包含
   target_authorization 的新精确计划，snapshot 绑定原 start/stop。无批准和错误 SHA 拒绝。
3. 正确批准后封存 Task，其 engineering/continuation policy 与计划一致；execute 不传
   自定义 route factory，使用生产默认 Configured 工厂。
4. 恢复 Task 第一次真实 0.5 秒超时，子进程组已停止，保留草稿；第二次同 Task/worktree/
   branch，使用新 Run/Context/WorkItem/Lease，并读取完整前次补丁和进度。
5. 注册 verifier 的 prepare/evidence 端口仅加观察，调用全部原实现核验 claim/current
   facts，完成后才允许 QA/Reviewer 的 offline provider 运行。此 fixture 计划是源码检查，
   不宣称执行 Python/MySQL sandbox 验证。
6. QA/Reviewer 使用不同 Agent、独立 worktree、同一 candidate；QA 通过真实受控只读
   `git show` 验证提交内容。原 Task/events、原完整 worktree bytes 和主 checkout 保留。

所有 provider 输入为本地 offline fixture。未伪造停止事实、注册发现或独立角色 verdict；
角色产物仍经真实 native adapter、候选提交、Schema、权限、artifact store 和编排门禁。

## 存量与回滚

本任务未改变持久化 Schema 或存量数据，无需迁移，也不操作已有 K1。回滚恢复旧入口调用和
seed 实现并重启服务；旧 Task、审批、历史与工作区均保留。实际修复的存量操作继续遵守
recovery-policy-freeze 任务中的精确新计划审批路径。普通交付参数作为 guard 保留。
