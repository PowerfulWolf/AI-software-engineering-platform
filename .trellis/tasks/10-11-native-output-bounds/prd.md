# Native 输出在运行期间保持有界

## 问题与目标

`SubprocessCodexCommandRunner._run_owned` 每 0.2 秒重试 `communicate`，但仅在返回时把
stdout/stderr 截断到各 1,000,000 字符。标准库在运行期间仍保存所有输出，长执行可不断占用内存。
修复真实 native 子进程读取，使内存与总输出量无关，同时保持已有调用协议、输出诊断和停止事实。

## 范围与允许路径

- `src/ai_software_engineer/agents/codex_cli.py` 与必要的私有 native 输出 helper。
- `tests/agents` 中的增量真实子进程回归。
- native 相关 `.trellis/spec/core` 契约与本任务目录。
- 基线 `fa8ffee`；仅隔离 worktree `ase-native-output-bounds`。
- 不调用真实 Codex/模型，不操作 ASE、服务、数据库，不修改生产主工作区或 K1 工作区，不提交推送。

## 验收

- [x] 真子进程在仍运行时的隔离 tracemalloc 断言先红后绿，证明运行期有界。
- [x] stdout 与 stderr 各最多 1,000,000 字符；超限保持相同 head/tail，尾部失败标记保留。
- [x] UTF-8 replacement、跨块字符与 CR/LF 通用换行语义不变。
- [x] 两条高输出 pipe 不死锁，不饿死超时和 ownership 检查；无读取线程遗留。
- [x] 匿名 prompt fd、继承 Task lock 与完整 prompt/EOF 保持。
- [x] TERM→KILL、leader reap、真实 EOF、group absence、native-stop callback 顺序保持。
- [x] escaped descendant 持 pipe、读取/收尾/记录异常 fail closed，不产生虚假 stop。
- [x] 相关增量 pytest、scoped Ruff/mypy、diff check 通过；不跑全量。
- [x] 独立复核，记录存量处置、部署限制与回滚点。

## 存量数据处置与回滚

没有 Schema/SQL/历史记录变化，不迁移或补造旧执行停止事实。旧运行实例尚未加载此修复；
仅在原执行安全结束后的受控维护边界部署。回滚私有读取实现即可，保留全部已封存事实。
