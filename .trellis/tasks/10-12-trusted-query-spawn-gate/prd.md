# 可信探测命令的启动归属门

## 问题与目标

实际 Darwin 本机执行调查在首个 `/bin/ps` 查询约 44–79ms 内变成
`PROCESS_SCAN_INCOMPLETE`。只读 trace 精确定位 `_DarwinInspector.identity:240` 的
`proc_pidinfo` count=0/EPERM。查询实际 exit0、stderr0，但初始 capture 已失败。

三个实际 ps 样本存活期间 euid=0、ruid=501，31–36ms 退出前持续 EPERM，
只读 `waitid(WNOWAIT)` 无退出事件；`/bin/ps` 实际有 setuid bit。两次普通 sleep 的出生身份
持续可读。这不是这轮样本的 zombie/退出竞态，是可信查询选择 setuid 可执行文件与
同账户 birth capture 不兼容。也存在普通短命工具先退出而捕获不了的独立启动竞态。

目标是在目标命令真正执行前捕获真实 isolated Popen 的 PID/birth/SID，再保持相同 PID
exec 原 token argv。不能把 EPERM 当停止、降低 registry 标准或补造旧 UNKNOWN。

## 范围与验收

- 新私有可信 spawn helper，固定版本 Python bootstrap，独立 session、私有 one-shot ACK。
- Parent 实际完成 owned capture 和复查后才释放 ACK；失败不 exec 目标、保存 uncertainty、
  清理真实已启动 leader。父子都关闭控制 FD，目标不继承控制通道。
- 只接入 `bounded_verification_command` 和 `TrustedLegacyLocalExecutionObserver._query`。
  原目标 argv/env/stdin/stdout/stderr/cwd 与 caller 既有超时/输出上限保持。
- 真实 Darwin setuid ps、极短目标、argv/env/stdin、拒绝 capture、权限拒绝、逃逸输出管道、
  FD 泄漏与真实清理都用有意义的窄增量测试；原 owned/schema 和对应 caller 回归保持。
- 不扩大 Agent 工具能力、Role 命令权限，不改变 Native Codex/Role execution 的 spawn。

## 存量数据与回滚

无迁移、无历史改写、无原 stop/READY backfill。PID802 的已捕获失败事实仍 UNKNOWN；
修复只改变新命令的真实启动顺序，故障 Host 的维护由 Root 独立处理。
回滚先受控停止修复版本，再回退本提交；保留所有旧记录及未知历史，不能为回退制造 READY。

允许路径见 task.json。Root 负责独立 review、集成和生产维护；本任务不自行提交未经 review
的代码，不合 main，不执行任何生产动作。
