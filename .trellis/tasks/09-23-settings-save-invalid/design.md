# 诊断与设计

## 证据

- 新开页面的未改动草稿经当前代码的 `UpdateSettingsRequest` 校验有效，不能证明旧浏览器标签或运行服务有效。
- 用户确认刷新原标签后仍失败，修改任意配置也失败；重启本机服务后可正常保存。
- 故障时只读 GET 的配置字段来自旧版服务：缺少当日新增的 Codex CLI 代理/连接方式契约。新版 `app.js` 从磁盘加载，旧 Python 进程仍保留启动时的 Pydantic 模型；`DomainModel(extra="forbid")` 将新版字段拒绝为 422。

## 方案

在 `SettingsSnapshot` 加独立的 `settings_contract_version=1` 响应元数据，不修改持久化的 `ProductionConfig`。设置页在保存前做精确版本比较；缺失或不匹配时保留草稿、阻止 PUT，并提示通过受管脚本重启后刷新。不能以可选配置字段是否出现作为版本判断，因为 `to_wire(exclude_none=True)` 会省略空值。

此方案不放宽服务端校验，不回显凭证。正常版本的保存行为不变，包括显式保存未修改的配置。
