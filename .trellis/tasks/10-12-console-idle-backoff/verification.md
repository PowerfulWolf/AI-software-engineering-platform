# 增量验证与存量处置

## 红绿回归

原 `1769977` 运行新假事件测试：**7 failed / 2 passed**，失败均为固定短间隔与期望退避不符。
局部实现后：**51 passed in 0.94s**：

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/web_console/test_idle_backoff.py tests/web_console/test_core.py tests/web_console/test_idle_replay.py tests/web_console/test_shutdown.py
```

新测试含默认/自定义等待、同进程提交、无新工作的幂等提交、真实独立 FileStore 外部提交、
成功/失败后重置、停止与解除停止；实际 claim 在每轮仍调用原端口。64次模拟默认idle
读取跨越约303秒，与固定0.25秒基线相比扫描频率减少超过90%。这是确定性调用频率验证，
没有声称已对生产 CPU/RSS 做修复后测量，也不是内存泄漏修复证明。

旧 core/shutdown 测试继续覆盖真实线程与关闭门禁；idle replay 测试继续拒绝历史同长度/
mtime 篡改、缺 parent、symlink，并发现另一个 store 的新操作。没有真实5秒测试sleep。

## 质量门

仅改动 Python 文件：Ruff check、format --check 均通过；`MYPYPATH=src PYTHONPATH=src`
strict mypy（独立cache `/tmp/ase-console-idle-backoff-mypy`）**2 source files / no issues**。
`git diff --check`通过。不运行全量测试，不使用生产模型、SQL、HTTP或service控制。

独立审查：root 对 `submit/run_once/_run/begin_shutdown` 的完整 Event/condition 路径复核，
确认清除在 claim 前，后到提交保留唤醒，停止门禁及自定义间隔没有阻断项。

## 存量数据处置

**无需改库或改写文件事实。** 等待index仅在当前dispatcher线程中，重启从初始值开始。
所有Operation、审批、Task、retry账、claims和工作区保持原内容，原完整store校验不变。
本提交仅在独立维护worktree完成，未部署，主仓/注册仓不修改。

## 已知限制与回滚

外部进程直接同store提交没有本进程Event；默认最多等待5秒加store读取/线程排队时间。
自定义初始poll>5秒仍保留原始最短间隔。本任务不解决完整operations列表或前端响应体，
该独立变更由其他任务承担。空闲受控部署可加载本提交；空闲时revert恢复旧等待频率，
无需回滚持久化数据。
