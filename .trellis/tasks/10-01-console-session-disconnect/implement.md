# 实施与验证

- 旧代码真实fake进程组回归RED：`test_background_service_survives_starting_session_termination`
  1 failed/2.70s，status显示服务消失。网络/404/503/invalid metadata四项UI回归RED，均错误
  显示“当前连接的是只读看板”。没有把此前生产进程的具体退出信号写成已证实事实。
- 脚本改用独立session+nohup，Console/supervisor/caffeinate分别脱离调用组。新版真实回归
  与配置apply 2 passed/7.16s；独立QA复跑受影响脚本模块25 passed/62.46s。
- QA指出新fixture等待无界，已改为内层8s timeout、外层10s select+有界os.read；独立QA
  复跑该fixture1 passed/2.65s，finding关闭。
- 前端严格区分404无接口与网络/5xx/JSON/契约失败，恢复后重算控制授权并保留草稿。
  readiness+ui 41 passed；追加JSON解析异常后5项Console定向回归通过。独立QA相关6项通过。
- Ruff/format、受影响测试文件Mypy、sh -n、git diff --check通过。独立Reviewer无遗留问题。
  不跑全量测试、MySQL测试或业务候选验收。

## 存量处置

旧启动会话与服务均已退出，无活跃Coder进程。新版管理脚本启动PID67715后，多个独立工具
调用读取Console、Team与Operation均成功，Console delivery_ready=true，未再随调用结束退出。
旧Operation `operation_f46b65e723e1a0c1a59f01f506c5e5e2`由正式startup处理为
HOST_INTERRUPTED；旧Task `task_recovery_e35017a761b1037b5a1318e151250922`保留
IMPLEMENTING及失效租约，最后heartbeat12:53:43Z，未直接改库。

继续提案 `operation_a99db3b82fe9d27c3b60a320d2d1c448`拒绝于WorktreeCaptureRejected：
原生中断入口只支持不变seed，但本轮Coder已产生合法新改动，现有20文件工作区保留。
这属于独立恢复能力缺口，K1还未重新执行；不把后台恢复宣称为业务交付完成。

实际Chrome复核工具因Codex auth token unavailable未能绑定页面，未伪造浏览器通过记录；
本轮前端验证依据真实app.js VM回归及服务HTTP静态资源。用户现有页面刷新可读取新版本。

回滚只撤销脚本与前端变更，在无活跃角色时重启；保留全部Task/Operation/审批/工作区。
旧nohup行为可能随调用组退出，长期运行应使用含独立session的版本。
