# 设计研究

原方向：复用 ExecutionBaselineService 的 exact 同 Task 草稿恢复与一次性 queue consumption，扩展 LegacyExecutionContainment 的工程隔离事实，而非增加第二套交付引擎。

备选方案：

1. 仅进程扫描、锁可获取或服务 PID 退出：不足以证明原本机执行及工具停止，不采用。
2. 整机重启：保留兼容，但不作为唯一正常用户路径。
3. 当前可信本机核验与精确工程处置：需确定观察的真实边界、存量未知事实和人工 provenance 的职责，先合同与负例测试再实施。

## 采用的契约

复用同 Task/原分支恢复，增加 `LegacyExecutionContainment.method=operator_confirmed_local_stop`，保留默认 `os_reboot` 的原 wire/digest。当前本机观察是辅助事实，不能声称扫描为空就证明历史全部停止；精确 `ENGINEERING` 操作者通过新字段 `confirm_local_execution_stopped=true` 提供原调用一直同机同账户本地、全部派生工具已结束、不再修改现场的声明，接受历史 UNKNOWN 并授权用剩余额度重新执行。原 `confirm_legacy_containment` 仍只确认整机重启，两字段互斥。

可信观察器仅接受受控已验证 WorktreeRef 的根目录和真实 OS boot，使用固定有界只读 OS 查询，不读环境变量、不保存原始 argv，不接受 HTTP 进程事实。仍有本机 Codex exec、工作区使用者、权限/查询失败、疑似或不完整观察时保留等待。Task 执行锁、全部 ACTIVE claims SQL fence、完整 snapshot 和双重 inventory/观察均需满足。

准备和消费必须 fresh 检查，但不能因新观察时间或无关系统进程变化导致原精确计划不可审批。使用 typed observation boundary 比较，复验匹配后保留原封存的 body/digest；新计划可重新准备，旧 authority 不改写。消费 crash replay 保留 original decision，完成消费后不重复扫描/扣预算。

Console contract version 3；旧版本 2 的 boot 计划仍可读/批，新无重启确认只接受 3。正常前提未满足返回 typed WAITING 检查结果而不是技术异常。所有 ValidationError 转固定中文，不能发布 input_value。

## 验证矩阵

| 情形 | 结果 |
| --- | --- |
| boot 早于原执行，完整安静本机观察+精确工程声明 | 同 Task 原分支保存草稿、追加新 WorkItem/Run/claim，旧 UNKNOWN 保留 |
| 只有空队列、自由锁或普通审批 | 拒绝，不产生新执行 |
| 关联/疑似进程或观察不完整 | 中文 WAITING 结果，无计划/审批 |
| boot/local 确认交叉或缺 Engineering duty | 拒绝 |
| 时间变化但 boundary/stable snapshot 未变 | 可审批，不改原计划 digest |
| 源码/索引/权限/设备账户变化 | 保留现场并拒绝，提供重新准备 |
| 封存 binding 后 SQL 消费前中断 | 原精确决定幂等重放，fresh 复验，无重复预算 |

## 文件职责

- 本机观察/containment：legacy_local_execution.py、legacy_containment.py。
- 后端组合/授权/消费：baseline_production/models/store、execution_baseline、production_host、legacy_audit。
- Console/UI：models/manager/transport、app.js 和浏览器/HTTP fixture。
- Schema/doc 同步：execution-baseline 嵌套模型、console-operation、legacy rescue 和 controlled restart 操作说明。
