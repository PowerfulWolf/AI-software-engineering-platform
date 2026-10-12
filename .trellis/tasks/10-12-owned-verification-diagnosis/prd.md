# 验证发现进程未知状态的原因保真

目标：受控验证探测的 owned-session 采集/收尾未知必须作为固定 typed 原因传播到
工程等待，不能误报 Docker 上下文、daemon 或 MySQL 镜像不可用。保留未知拒绝边界。
使用真实 registry、真实 bounded_verification_command、独立短命假 Docker 可执行文件和
Inspector 注入复现；不改变 owned-session、registry 或 service lifecycle 实现。

验收：

- 新增 `VERIFICATION_PROCESS_STATE_UNCONFIRMED` 领域枚举及发布 Schema；只把真实
  `OwnedProcessesUncertain` 映射到该原因，所有三个 Docker 命令边界原样保留它。
- 真正的上下文、daemon、镜像失败仍得到原原因，普通 RuntimeError 不被当作停止未知。
- native verifier、preflight 与工程等待保留 typed 原因；中文说明不能要求拉取镜像，明确
  原执行停止/收尾事实未核验及复查前提，不增加恢复权限。
- 后两次真实 discovery 成功不制造原 stop proof；原 registry 仍 uncertain 且拒绝关闭。
- 结果只证明该代码路径可发生，不将生产 PID 802 首次失败的实际原因宣称为已证实。

允许路径见 task.json。验证使用上述增量 pytest、Ruff、strict Mypy 和 diff check。
RED 已确认：真实 image 阶段 owned capture 未知被错误包装成 MYSQL_IMAGE_UNAVAILABLE。

存量数据处置：不改库、不重写历史、不补造 stop proof。旧误分类记录保持原 bytes/digest；
新原因只适用于修复版本的新观测。已 sticky 的旧服务另由 Root 的受控诊断流程处理；本任务
不操作生产、不重启、不批准或继续 K1。后续两次 READY 不清除历史 unknown。

回滚：在受控停止后回退本任务代码及 Schema。保留已发布的新原因记录，不将其改写为镜像
错误；旧读取器不认识新 enum 时应拒绝读取，不能删除字段或改写 digest。
