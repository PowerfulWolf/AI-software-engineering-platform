# 私有实际启动门设计

`owned_spawn.spawn_owned_query` 接受可信 caller 已经决定的原 tokenized argv、明确环境和
stdio/cwd。启动固定 bootstrap 的真实 Popen，`start_new_session=True`、`shell=False`，
只继承内部 ACK 读取 FD。bootstrap 以 `-I -S -B` 启动，不读取用户 site、PYTHONPATH 或
可注入 module；固定版本校验后等待私有一个字节，EOF/错误则退出，不执行原命令。

parent 调用既有 `observe_owned_process(kind=tool)` 并调用 `observe_session()` 重新验证；
二者都发生在 ACK 之前。成功后发送一次有界 ACK frame、关闭控制 FD，bootstrap 完整校验并
关闭读取 FD再 `execvpe(original_argv[0], original_argv, original_environment)`。exec 保持真正 PID/SID/birth；
helper 返回同一个实际 Popen 与其原 observation，caller 不重新捕获。

ACK frame 为 `b'1'`、4字节big-endian body长度与至多2MiB的ASCII JSON原环境字典；
2MiB超过这两个可信callers现有有界allowlist值且不增加OS真实exec容量。JSON不上argv/日志。
Python bootstrap会添加locale/macOS内部变量，不能直接用它的`os.environ`启动目标；必须
从私有frame恢复原字典。因此空环境和显式allowlist都保持精确，不能混入bootstrap新变量。
部分frame/EOF/非法类型/超限都退出125不执行目标；目标exec权限拒绝退出127无原异常文字。
parent以nonblocking pipe+可写select发送frame，内部最多1秒；未读取/部分发送不会无期限
卡住caller。原目标执行时限仍由各caller原来的timeout控制，不将私有ACK当执行结果。

Darwin setuid ps 的运行阶段 kernel birth 可能仍不可读；helper 不对此作停止推断。现有
query 等待真实命令返回、reap，并执行原 owned stop 两次完整 empty sweep。若 timeout
或身份仍不可验证，保持原 fail-closed 行为，不强制通过。启动门也避免普通快速目标在
首次 capture 前消失，但不承诺完整进程树 containment。

所有启动/capture/ACK 故障都在 helper 内关闭私有 FD；已经有实际 Popen 的失败路径只
清理这个由父进程持有的 leader，不扫描或随意 kill PID。目标尚未获 ACK，不能产生工作。
真实未知仍留在 registry；不得用 cleanup 成功消除 uncertainty。

新 helper 不是 Agent tool，不执行授权、Role verdict、Artifact、状态或恢复。两个既有可信
callers 保留各自 input/output/timeout 预算和固定失败映射。不存在新持久化或 Schema 字段。
