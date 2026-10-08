# 工程中断的产品操作路径

## Goal
用户作为产品使用 ASE，只处理业务决定及真实新增授权。Manager 通过确定性 typed 服务在冻结授权内核验和恢复技术中断，用户不应核验 lease、停机证明、hash 或工作区。平台缺陷不能隐藏在反复调查按钮或“找维护者”文字中。

## Scope / allowed paths
domain/engineering_authority、delivery_resolution；manager/delivery_wait、production_host；work_queue 的 resolution 消费与 invocation；agents/codex_cli 与 continuation ports；orchestration/continuation_models、store、continuation；Console models/manager、team_view UI/engineering_history；相应 schemas、增量 tests、docs、spec。

## Acceptance
- 新 HANDLE_DELIVERY_WAIT 精确绑定同一 Project/Requirement/Task/等待，执行一次有界收集和调查，完整安全证明与冻结策略允许时自动恢复原需求，不冒充人工审批。
- 人工、策略与平台故障处理分别持久化审计；旧任务不追溯授权、旧事实与 digest 不变。
- 找回原 sealed route final 结果，不重调模型；只有 FALLBACK 或未知产出时拒绝补造 outcome。
- 原执行前库存与真实停止事实提前封存，支持 stop 后 receipt/outcome 前崩溃的事实补齐，不用新 claim 冒充旧 Worker。
- 无可信旧事实仍保留等待与完整现场，形成具体可读处理记录，不虚称已派人或已继续。
- 当前展示说明原因、责任、用户具体动作与复查时机；重新调查不作为无效的主操作；技术身份折叠，历史不冒充当前建议。
- 队列 source/claim/budget/verdict gates 与独立 QA/Review 保持，负例和公共入口增量验证通过。

## Constraints / rollback
不操作用户当前 ASE、不审批或继续真实交付、不重启服务、不改生产数据库、不读凭证。仅增量测试；全量由用户决定执行。回滚前空闲停止服务，回滚代码时保留新增 immutable record readers；不删除现场与审计。旧无before/stop资料的运行不能补造记录。
