# 真实离线进程的终态恢复 E2E fixture

## 问题与目标

`test_recovery_complete_native_delivery_and_preserve_failed_history` 的三个参数 case 使用普通
`InterruptedFactory` 直接改文件并返回失败。当前新 Task 带 continuation policy，但这个测试
factory 不经过真实 configured adapter / NativeCoderContinuation，因而没有合法 execution
capture-start / process-stop，现代终态完整审计在恢复 proposal 前拒绝。

只修测试夹具，使真实 Git、隔离 MySQL 和离线 provider 的恢复链覆盖现行审计要求。
原始失败须经真实 ConfiguredDeliveryRouteAdapterFactory、CodexCliAgentAdapter 和
SubprocessCodexCommandRunner 执行 tmp 下的离线可执行脚本；停止事实必须来自真实子进程回收
与进程组检查。不得伪造 NativeProcessStop、直接补 store 记录或 monkeypatch 核心审计。

## 范围与所有权

只拥有 `tests/recovery/test_execution.py`、必要时新增的专用
`tests/recovery/execution_fixture.py` 及本任务目录。保留 `test_native` 通用 factory 和生产
gate；其他 Agent 同时工作，不回退他人的修改，不修改 UI 或其他测试。

先原样跑目标三个 case 记录精确红测，再实现最小 fixture 修复。真实模型/网络不参与；
原 Task/事件/现场不可变、恢复精确审批、seed/input_mode、独立 Coder/QA/Review 及 candidate
一致性断言均保留。契约仍缺失时先报告，不扩大到生产改动。

## 验收与验证

- 三个 case 原 fixture 在现代终态审计前失败，记录异常链。
- 原始失败拥有平台自然封存的 start / stop 与真实 claim，不以构造的 stop 证明替代。
- strict seed、coder_reapply 和 legacy direct-commit source permissions 三个 case 均到 DONE，
  原失败历史和工作区保持不变。
- 同步记录准备观察的真实阶段边界，不把预分配当作真实 Coder claim。
- 只用已存在 `ASE_TEST_MYSQL_DSN`。运行前通过现有测试库命名 guard，并只比较本轮生产配置
  sibling runtime.env 中 DSN 的解析库名，确认两者不同；不打印 DSN、环境或 provider 正文。
- 仅串行跑目标三个 MySQL case，再做修改文件的 Ruff/格式/strict mypy；不跑全量。

## 存量处置与回滚

仅 tmp Git/worktree 和独占测试库产生测试事实，生产无写入、迁移、重启或审批。测试库按既有
autouse fixture 前后清理。回滚限本任务测试及专用 helper，不影响生产授权或历史。
