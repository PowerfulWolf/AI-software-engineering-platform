# 后台服务退出与控制接口断连

2026-10-01用户再次看到“交付控制不可用”。沙箱外curl确认8765无监听；原PID36198及
运行会话已消失。用现有脚本start显示PID64347启动成功，日志确认8765启动，下一次独立
读取时服务、监督器均消失，没有异常栈。当前证据指向调用会话结束影响后台进程，但不能据此
断言此前进程收到的具体信号。UI catch还把所有网络/协议失败写成“当前连接的是只读看板”。

## 目标与范围

- 后台Console、监督器及防休眠进程脱离启动调用的session/process group；真实PID、
  安全身份检查、单监督器锁、配置应用、write-only环境加载保持不变。
- 网络、5xx、响应损坏代表控制连接未知，不代表只读看板；404缺少Console入口单独处理。
- 保持交付操作fail closed；恢复连接后自动移除故障提示、恢复适用操作，不丢表单草稿。
- 用管理脚本恢复服务，通过原生中断恢复接续K1；不直接改库或手改业务worktree。

允许路径：scripts/ase-console-service.sh、tests/test_console_service_script.py、
team_view/app.js、tests/team_view/readiness.test.cjs、本任务、web-console规范和部署文档。
基线d0895f7。只跑新增进程/断连回归、相关脚本生命周期和前端增量测试。

验收：独立启动进程组退出/TERM后服务及监督器仍在、状态及stop仍正确；明确断连/只读
提示和重连；实际HTTP稳定恢复；原K1完整历史保留，新的执行必须有真实claim。
回滚：回退代码、仅在无活跃角色时重启；保留所有审批、Task、worktree与历史。
