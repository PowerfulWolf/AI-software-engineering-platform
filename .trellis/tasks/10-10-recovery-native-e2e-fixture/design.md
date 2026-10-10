# Fixture 契约

## 原失败必须是真的受控执行

测试创建 tmp 可执行脚本，使用当前 Python 的绝对路径作为 shebang。脚本只在平台选定的
Coder worktree 写 `hello.txt`，输出固定的离线 authentication failure 后退出 1；没有模型
SDK、网络、真实 provider 输出或密钥。该固定非 transient 故障用于终态恢复场景，不伪装
成实际供应商事故，也不申请自动重试。

Host 不再注入普通 `InterruptedFactory`，由正式 ConfiguredDeliveryRouteAdapterFactory
创建 CodexCliAgentAdapter，并接收真实 WorkerExecutionGuard / NativeCoderContinuation。
默认 SubprocessCodexCommandRunner 启动真实隔离进程组、回收输出、核对进程组消失，再将
真实 NativeProcessStop 经正式 observer 封存。测试只读取 capture-start/stop，验证
request/claim/digest/时序和当前进程组缺失；没有直接写 continuation store。

源 permissions 的 legacy direct-commit 参数仍是原有显式历史 fixture。恢复 target 重新
编译现代 permissions，断言没有 `git commit`；该参数并不让 offline Coder 执行提交。

## 真实知识与前提 gate

configured delivery 会创建独立知识模型客户端，而 Host 的 structured_clients 只负责上游
stage。测试在 `ConfiguredStructuredClientFactory` 模型构造端口注入专用 offline client，
保持知识准备、claim、context 和 preflight 全部真实。

该文本仓库没有可推断测试入口。专用 Designer 显式声明 hello.txt 的 source inspection
及比对清单，冻结进 TechnicalDesign / ExecutionPlan；Product exact approval 和现行阶段
契约保持。不能把 `test_levels=acceptance` 当作可执行测试入口，也不 monkeypatch preflight。
独立 QA、Reviewer 分别用机器 read policy 和 exact candidate `git show` 比对批准的 greeting。

## 恢复成功侧与观察

恢复 provider 仍使用离线 runner，但它调用真实 CodexCliAgentAdapter。Coder 只写已授权的
hello.txt 并返回绑定输入 SHA 的 provisional implementation-report；真实平台
CandidateCommitSkill 创建 candidate。QA/Reviewer 是不同 dispatch Agent，各自只读独立
worktree，仍由既有正式 artifact 和状态门禁确认 DONE。

一个 typed ConsoleOperation 精确绑定项目、原交付 checkpoint 和 plan；测试只将其作为
observer scope，不宣称完成生产 HTTP 操作。approve/execute 周围挂正式 observer 和独立
文件 store。授权+封存后只允许两项，route factory 前只允许前四项；结束后必须可只读
重开全部五里程碑，真实 EXECUTION_CLAIMED 对齐 Coder Context 中的 WorkItem/Lease/Assignment。
观察不是授权或 heartbeat，不能由三阶段预分配代替真实 claim。

## 保留与测试范围

原失败 Task/events、旧 worktree 全字节快照保持，恢复精确批准、错误批准拒绝、seed 漂移
拒绝、strict seed conflict、coder_reapply、候选 SHA 一致性与幂等恢复断言保留。
只修目标三个参数 case；joint-child 和其他 `test_native` 普通 factories 不在本任务范围。
本 fixture 走完整 terminal snapshot 路线，与 f88 的非 snapshot 来源不同，耗时不能作为
生产 f88 根因或优化收益证明。
