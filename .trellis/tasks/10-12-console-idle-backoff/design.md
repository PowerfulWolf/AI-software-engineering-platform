# 设计与研究

## Relevant Specs

- `core/python-runtime.md`：typed ports、strict 类型和稳定错误边界。
- `core/web-console.md`：持久化用户意图、后台 Manager、完整 Operation 验证。
- `core/read-memory-lifecycle.md` 的 idle dispatch：每次 claim 完整 bytes 校验，不能用 mtime。
- `core/controlled-service-restart.md`：停止提交/领取后等待真实执行和最终持久化。

## Existing Patterns

- `ProjectConsole.submit` 在 store.submit 成功后 `_wake.set()`。
- `begin_shutdown` / `cancel_shutdown` / `_refuse_locked` 共用现有 `_wake`。
- `tests/web_console/test_idle_replay.py` 覆盖同长度/mtime 历史损坏、外部提交和路径变更。

## 实现 seam

仅 `ProjectConsole._run()` 使用局部有限等待序列和 index，不添加 durable 调度索引。
序列为 `(poll_seconds, max(poll_seconds, 1), max(poll_seconds, 2), max(poll_seconds, 5))`；
保持自定义初始轮询参数为最短等待，默认最大 5 秒。每轮实际 claim 前清除旧唤醒，
使清除前已持久化的操作由当轮 claim 发现，清除后提交的操作由 Event 提醒。
wait 被唤醒或执行了真实 Operation 后重置 index；超时仅增加到最后一级。

## 验证矩阵

| 场景 | 断言 |
| --- | --- |
| Good：默认持续空闲 | 0.25→1→2→5，之后始终5，实际 claim 每轮执行 |
| Base：外部 writer 无本进程 Event | 下一 timeout 后发现，默认等待不超过5，完整 store 校验 |
| Bad：同长度/mtime 历史损坏 | 原 idle-replay 测试继续拒绝，不以退避缓存授权 |
| 同进程 submit / 重复提交 | 立即唤醒，下一空闲等待回到0.25 |
| Operation 成功/失败 | 原结果照常封存，随后空闲等待回到0.25 |
| 停止 / 解除停止 | 等待不阻挡停止；解除后从初始等待恢复 |
| claim 或最终记录失败 | 原 REFUSED latch 不变，不能变成 idle READY |

## 验证命令与回滚点

使用主仓虚拟环境 Python，以本 worktree `PYTHONPATH=src MYPYPATH=src`：
`pytest tests/web_console/test_idle_backoff.py tests/web_console/test_core.py tests/web_console/test_idle_replay.py tests/web_console/test_shutdown.py`，
以及只检查改动 Python 的 Ruff/format/mypy。回滚点为 `1769977`；仅回滚代码，无数据修复。
