# 完整恢复记录读取与明确操作入口

## 问题与根因

用户在原 K1 需求准备保留进度恢复后仍看到 EXECUTION_UNCERTAIN，且所有操作按钮消失。
只读调查发现最新操作已 SUCCEEDED，legacy_rescue_preparation.status=READY，记录本身
通过 model、digest、sequence 和 hash chain 校验。完整恢复结果为 2,177,461 bytes，
FileConsoleOperationStore._current 却使用通用 Team 文档的 256,000 bytes 限制。
GET /api/v1/operations 和单条 GET 因此返回 500；前端 operationsAvailable=false，
canControlCurrentTeam=false，恢复和工程等待控件隐藏，但没有持久说明。

## 目标与范围

- 独立、有界的 Operation serialized UTF-8 JSON bytes 预算，读写一致；不复用知识正文预算。
- 完整读取既有合法 2.18 MB 恢复结果，不截断或重写 patch、记录、hash 或审批。
- 超限写入在发布文件前拒绝；损坏、超限、路径和完整性读取错误返回中文安全 503。
- 工程等待和恢复面板明确说明按钮不可用的原因与下一步，文案和控制门禁一致。
- 能力、Team、Project、当前版本、精确审批、旧闭包检查保持；读取失败不能复用旧计划批准。

本轮不替用户操作 ASE，不审批、不启动 Coder、不重启生产服务、不修改数据库或原 worktree。
不扩展交付权限、重试预算或状态机，不重建需求，也不将完整计划改为新的 wire 引用结构。

## 验收

1. 真实 Git fixture 产生超过 2 MB 的完整计划，store reopen/list/get 与 HTTP list/detail 返回完整结果。
2. 16 MiB 上限按实际编码 bytes 包含 JSON escaping 衡量，超限无终态文件与临时文件。
3. 大记录的 model、digest、hash chain、文件名与安全路径仍校验，损坏 fail closed。
4. 操作读取失败时 Console readiness 保持独立，交付禁用且原因在需求内持久可见。
5. Console 不可用、runtime 未就绪、Team 不符、Project 切换与能力缺失不承诺不存在的按钮。
6. 数据重新可读后原方案重新显示；必须再次独立确认，旧控件或缓存不得越权提交。
7. 只读验证原 2,177,461 bytes 记录，文件 bytes/hash 不变；增量检查和独立审查通过。

## 存量数据处置与回滚点

原 Task、Run、操作链、草稿、数据库与审批均不迁移、不修改。修复服务加载后兼容重新读取
同一操作，显示已经保存的 READY 方案，用户仍需工程职责确认。回滚到本轮基线时使用
受控停服/启动，不删记录或进度；旧读取限制可能再次令大记录不可读，这是已知回滚影响。
