# 新恢复授权的生产组合验证

纯模型/Builder测试证明目标授权冻结，但旧recovery测试使用OfflineFactory，没有覆盖
真实Configured工厂对NativeCoderContinuation和RegisteredNativePythonVerifier的装配。

在现有public native fixture增加一个恢复case，普通交付case保留作为guard。原执行与恢复
中的中断均使用真实受控子进程和停止记录；恢复通过formal propose→exact approval→默认
execute，不传自定义route factory。验证同恢复Task/worktree、全新claim、保留进度，及QA/
Reviewer不同Agent和独立候选检查。注册验证端口只包观察并调用原实现，不伪造发现或停止。

范围包含恢复入口/续跑的 Requirement 作用域传递、seed 后目标 index 归一化，以及
tests/manager/test_production_continuation.py 和本任务记录。不改其他 worker 行为，不调用
真实 provider。静态通过后由根代理协调隔离 MySQL，只跑新增 case；guard 仅在必要时补跑。
不得全量测试。

验收：两policy和原预算进入新批准方案及封存Task；无批准/错SHA不能execute；实际中断
有start/stop/receipt，续跑有新WorkItem/Lease；注册准备和证据端口真实核验claim/facts后
才调用QA/Review模型；candidate三方一致；旧Task/events/worktree和主checkout保留。
