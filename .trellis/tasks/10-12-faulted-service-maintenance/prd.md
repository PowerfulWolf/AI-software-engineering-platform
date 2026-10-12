# 精确故障服务替换为只读检查服务

目标：旧Host进入stickyREFUSED且读取服务损坏后，提供可审查、可重试的本地维护入口，完整
封存旧记录和日志，真正结束精确旧writer后恢复只读前端。用户此次不继续需求。

范围：fault_retirement.py；本地maintenance CLI；lifecycle dead/initial只读fallback；
service.sh mode/apply gate；只读OS身份seam；固定schema与tests/spec/docs。Host/transport/UI
inspection由并行worker负责。旧service_maintenance.py/test原型保留tree、不stage或启用。

验收：实际隔离Host+supervisor完整prepare/execute；原REFUSED/UNKNOWN原字节不改；完整log
同inode/SHA归档；actualexit；marker永久inspection；错identity/confirm/config/bytes/frozen
不signal；每个中断阶段同plan可重入；live unknownwriter拒绝；normalenv不能覆盖；坏marker
任何writer创建之前拒绝；普通READY行为不变；仅增量测试。业务需求恢复不在本轮范围。

回滚：保留inspectionmarker/档案兼容reader，不能删除marker或退到会normal启动的旧binary。
