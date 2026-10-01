# 契约

`launch_detached(argv...) -> pid`：脚本内部Python subprocess入口，固定shell=False、
start_new_session=True、stdin DEVNULL、stdout/stderr现有日志。返回真实子PID，启动错误
只输出稳定摘要，不打印继承环境。nohup保留忽略SIGHUP行为。Console与监督器分别独立
session；caffeinate仍绑定真实Console PID。既有身份检查与锁不得放宽。

`refreshConsoleInfo(signal)`：成功校验v0.2/team_id/delivery_ready后available=true；
HTTP404设置false（当前服务无Console接口）；网络/其它HTTP/JSON/contract失败设置null，
清除Team和ready授权事实，并记录断连提示。初始未读取与读取失败需可区分。
所有失败均禁用控制；恢复成功清除故障，无Task/Operation/Schema写入。

Good：启动工具退出或发送原组TERM后，服务继续运行，配置apply/stop仍精确可用。
Base：只读服务404，显示无控制接口；网络断连显示连接不可用。
Bad：外来PID、symlink、非法runtime.env仍拒绝；网络断连不能声称只读、成功或任务失败。

先测真实fake服务在原调用session终止后的存活，再实现；前端用现有VM执行真实app.js，
覆盖断连→重连、404、503、invalid JSON/schema及保留草稿。无需全量测试或改持久Schema。
