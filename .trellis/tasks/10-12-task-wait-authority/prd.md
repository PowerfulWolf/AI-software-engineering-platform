# Task 隔离的工程等待授权

原 K1 基线 PAUSE 已成功；独立 RESUME operation_9d60ce47bda23ddc9dd58813b43ad721 在
07:21:50Z 拒绝 `recovery record already has different content`。原 source 已 f91f33a，
主 Coder 未启动，知识 intent 已成功；当前等待由注册验证前提产生。

确定根因是 `_resolve(automatic=True)` 将所有 Task 的 local authority 放在仓库同一个
`state/delivery-wait-authority/`。其 scope.json 已绑定旧 Task 8ca06...，新 Task 455883...
的 scope delivery_id 不同，immutable store 正确拒绝覆盖。

## 验收

- 本地工程授权按可信 Task ID 的 SHA 隔离，仍使用私有 scope 校验的 FileRecoveryStore。
- 旧 scope/admission/决策字节保持；新 Task 不读取或复用别的 Task 本地权限。
- 同 Task 全局共享 EngineeringAuthority ledger 继续计费，已封存 partial admission 恢复
  exact 原序号及时间，不退预算；同决定重复消费保持幂等。
- 新 root 损坏/跨 scope/unsafe 拒绝，不能回退固定旧 root；无新模型/停止/verdict权限。
- 真实 public handler 在固定旧 scope 已存在时 RED→GREEN；相关 crash/replay/权限增量通过。
- 存量 K1 发布后 fresh公开读取等待，通过原平台处理入口核验前提并继续，不改 SQL 或旧错误。

## 允许路径与验证

仅 task.json 中路径。增量 pytest 精确新增节点和既有 handling replay/policy 节点；Ruff/format、
strict mypy、diff check。无全量、无生产模型测试。发布前独立审查和全局 idle/受控 stop。

回滚点 f91f33a；新root开始封存后保留兼容代码和历史，优先forward fix。
