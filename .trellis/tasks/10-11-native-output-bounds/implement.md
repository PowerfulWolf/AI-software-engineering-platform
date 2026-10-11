# 实现与验证范围

- 私有 `_NativeOutputDrain`：单线程 selector、两流公平固定块读取、0.2 秒 drain 窗口；
  每流独立增量 UTF-8/通用换行 decoder、固定 head/滚动 tail，实际 EOF 单独记账。
- runner 保留匿名 prompt fd 与 inherited lock、guard/watchdog、TERM→KILL、leader reap、
  group absence 与真实 stop publication；输出资源在 publication 之前关闭。
- 读取/selector 初始化或关闭失败、任一 pipe.close 失败均保留 Host uncertain；callback
  异常不二次发布，owner 在 publication 后丢失仍保留已记录的真实停止事实。
- `CodexInvocationResult`、公开 runner 签名、模型参数、Schema、诊断/hash 的输入文本语义不变。
- 复用原 `_bounded` 的字符上限常量；未改变其他受控命令执行器的 byte budget 或线程实现。

## 质量与部署

只运行本次影响的增量测试与 scoped Ruff/mypy。没有真实 Codex/模型调用、ASE/服务/DB 操作、
commit 或 push。生产 main、K1 worktree、原有需求/Task/审批/停止事实都没有修改。
本地修复不等于已部署，也不能关闭旧 unknown 执行；需 root 在实际执行空闲后按受控维护流程装载。
