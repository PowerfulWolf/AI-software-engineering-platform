# 增量验证与限制

基线 `fa8ffee`，隔离分支 `codex/native-output-bounds-20261011`，日期 2026-10-11。
环境 Python 3.12。命令中的 `PY` 指向主仓既有 `.venv/bin/python`，`PYTHONPATH=src` 指向
本隔离 worktree 源码。没有安装依赖、运行全量测试、调用 Codex/模型或操作服务/ASE/数据库。

## 先红后绿与运行期内存

```text
PYTHONPATH=src $PY -m pytest -q tests/agents/test_native_output_bounds.py
```

旧 runner 红测：`1 failed in 0.79s`，`running output retained 16841017 bytes`。
真实 Python 子进程同时写两条各 8 MiB 输出流，写完后仍等待 release；ExecutionGuard
在此时采样 tracemalloc，再释放子进程。最终输出已被旧 runner 截断，红测测的是仍运行期间
标准库沟通缓冲，不是返回后的结果长度。

修复后同一隔离 driver：运行期间 current `2,009,515` bytes，peak `3,206,203` bytes；
returncode 0、无 timeout，stdout/stderr 各 1,000,000 字符，分别保留尾部失败 marker。
断言 current <6 MiB、peak <12 MiB。输入为有限小规模 fixture，不制造 GB 级压力。
该结果证明本 runner 输出累积缺陷，不单独证明生产全部内存告警都源于该缺陷。

## 120 个独立增量用例

```text
PYTHONPATH=src $PY -m pytest -q \
  tests/agents/test_native_output_bounds.py \
  tests/agents/test_codex_cli.py \
  tests/agents/test_structured_observation.py \
  tests/agents/test_structured_execution.py \
  tests/execution/test_owned_processes.py -k 'not mysql_proxy'
```

第一轮 `105 passed, 1 deselected in 36.43s`。仅排除不相关 MySQL proxy fixture；当时新文件
含 13 个展开用例。保留 structured 原有失败分类、真实停止、初始化失败与 observation 回归。

独立审查建议补齐任一 pipe.close 故障及 escaped descendant 仅持一条 pipe：

```text
PYTHONPATH=src $PY -m pytest -q tests/agents/test_native_output_bounds.py \
  -k 'either_pipe or escaped_descendant'
```

`4 passed, 13 deselected in 0.67s`。两条资源都关闭，callback 未执行，Host 保持 uncertain。

匿名 prompt/完整 EOF、timeout、graceful TERM、group proof 与 owner loss 回归：

```text
PYTHONPATH=src $PY -m pytest -q \
  tests/work_queue/test_owned_execution.py::test_owned_codex_delivers_large_prompt_after_first_lease_poll \
  tests/work_queue/test_owned_execution.py::test_owned_codex_timeout_terminates_child_after_prompt_delivery \
  tests/work_queue/test_owned_execution.py::test_local_limit_records_actual_graceful_exit_without_claiming_completion \
  tests/work_queue/test_owned_execution.py::test_owned_runner_refuses_every_result_without_group_stop_proof \
  tests/work_queue/test_owned_execution.py::test_lost_owner_terminates_executor_before_returning
```

`9 passed in 9.83s`。包括真实 delayed Unicode prompt、0600/zero-link stdin 与正反向
process-group stop proof，未运行已知旧 unrelated 启动错误文字断言。另补真实 inherited Task
descriptor 用例，验证 child 可以读取显式继承的 descriptor，parent descriptor 保持可用。
该用例 `1 passed in 0.10s`。另补半途 selector 初始化失败用例：第一条 pipe 注册成功，
第二条注册抛错，所有已打开 selector 和两条 pipe 均关闭、child reap、Host uncertain，
`1 passed in 0.17s`；随后重跑三文件 scoped 检查通过。

## Scoped 静态检查与质量门

```text
PYTHONPATH=src $PY -m mypy --follow-imports=silent \
  src/ai_software_engineer/agents/_native_output.py \
  src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_output_bounds.py
$PY -m ruff check <同三文件>
$PY -m ruff format --check <同三文件>
git diff --check
```

严格 mypy：`Success: no issues found in 3 source files`；Ruff：`All checks passed!`；
format：`3 files already formatted`；diff check 无输出。
独立 reviewer `/root/recovery_read_cost/task_projection_reuse` 只读复核最终 runner、helper、
异常/EOF/observer 路径与 specs，结论无阻塞项；reviewer 未重复运行测试。
按 before-dev/check/finish-work 读取适用 core/native/shared specs；仓库不存在
`.trellis/scripts/get_context.py`，按 core/guides index 手动发现，未创建替代工具。

## 契约、存量与部署

无 Schema/接口/SQL/Task/审批/角色权限变化。新增私有 drain 只依赖标准库；公共 runner 与
`CodexInvocationResult` 保持，structured observer hash 仍绑定相同 bounded normalized 文本。
未改通用受控命令的 byte-budget/thread collector；其截断协议与本 runner 的字符 head/tail 不同。

存量数据无需迁移：保留全部原需求、草稿、未知停止与失败记录，不补造被丢弃输出或旧停止事实。
生产服务尚未加载修复，本任务没有中止或重启 K1 执行；第6轮随后真实停止并进入完整进度封存
等待，原停止与草稿保留。本内存修复不补齐其缺少的封存记录，root 在确认真实执行空闲后受控维护部署。
回滚 runner 私有 drain 与规范段即可，保留所有 immutable 审计事实。
