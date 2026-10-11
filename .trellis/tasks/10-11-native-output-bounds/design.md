# Native 输出内存边界设计

## 契约

保留 `CodexInvocationResult`、runner 公共签名与停止 observer；不加 `--json`、新的持久化观察或
协议字段。每个输出流保留最多 1,000,000 个解码后的字符，溢出后固定前 500,000 字符与滚动
后 500,000 字符；中间文本及时丢弃。私有缓冲仅属于本次同步调用。

## 实现计划

1. 真子进程输出 stdout/stderr 后继续等待；guard 在运行期间测内存并解除 fixture 等待。
2. POSIX selector 同时读取两 pipe，单次每 ready stream 只读固定大小块；每轮 drain 受 0.2 秒
   截止时间约束，持续输出也不能延长 ownership/watchdog 检查间隔。
3. 每流独立增量 UTF-8 replacement decoder 与通用换行 decoder；EOF 时 flush，不能按块独立
   decode 或因关闭本地 fd 推断 EOF。
4. 运行、超时和异常 cleanup 复用同一 drain 与有限缓冲。先 TERM，最多 1 秒后 KILL，再最多
   1 秒 drain/reap；输出 EOF 与进程组不存在后才 publish real stop。
5. 所有 selector/pipe 在 finally 关闭；无后台读取线程。初始化或清理异常保留未知停止语义，
   尽力停止实际拥有的进程，绝不发布 NOT_STARTED 或把本地 close 当作 EOF。

## 风险与验证

重点覆盖 Unicode/换行边界、两流公平性、持续输出超时/owner loss、逃逸后代持 pipe、observer/
registration/close 失败。内存测试隔离进程且使用小规模有限输出，不模拟 GB 级压力。
读取块与字符串拼接会有有限临时分配，字符上限不是整个 Python heap 的精确字节上限。
