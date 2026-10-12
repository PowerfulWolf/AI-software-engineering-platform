# 实现：精确故障Host退休后恢复只读检查（2026-10-12）

原foundation设计不启用、不提交。实际实现采用更窄契约：旧writer确已结束、原字节完整归档，
继任只能inspection，没有TeamHost/dispatch/index/任何HTTP mutation，不继续需求。

新fault_retirement.py与受信本地maintenance CLI从官方固定文件和OS自行采集Plan，精确bind
boot/birth/session/frozen/executable/argv/原instance时间（60s启动窗口），先TERM固定且已验证
supervisor、再SIGKILL精确Host。原日志同FS移动，保持dev/inode/size，退出现有writer后有阳性
sentinel的lsof调查并stream全SHA，生成实际executorreceipt和永久inspectionmarker。

保留原REFUSED/UNKNOWN和所有业务事实。scope/catalog未知只明示UNKNOWN；没有旧Run停止、
QA/Review通过、数据库一致性或需求安全可继续的声明。角色/HTTP无法调用维护executor。

CLI dead/initial添加只读receipt fallback；launch-mode/host持久marker优先，normalenv不能
覆盖。120s只读启动等待覆盖大日志hash；配置apply在inspection拒绝。独立inspection worker
负责Host/transport/UI入口，无writer构造，root合并真实marker组合测试。

实际阶段intent→move/chmod→kill/ack→stable loghash→receipt→marker可同plan重入。kill后只
finalize、不重发其他PIDsignal；ack未保存保留signal_sent UNKNOWN/None。原scope或原字节漂移
拒绝。static schemas、原文件安全、lsof退出码和每file字段边界都有增量测试。

验证结果见validation.md。所有真实进程测试仅隔离child/controller，没有生产动作。rollback
必须保留marker与只读reader，不能启动不认识marker的旧normal服务。恢复交付另行工程处理。
