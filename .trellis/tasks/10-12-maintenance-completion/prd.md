# 完成维护并恢复普通模式

目标：提供本机受控维护完成入口和前端可发现的操作指引。恢复普通模式与需求审批、执行恢复分离。

范围：独立 maintenance_completion typed service、完整只读队列检查、append-only plan/receipt/admission；服务脚本两步入口；生产 Host 写入前 gate；维护横幅指引；静态 Schema、增量测试和规范。

验收：
- 只有当前 inspection successor 的精确 SHUTDOWN/READY 和实际 PID 不存在才可准备；旧 REFUSED/UNKNOWN 不变。
- 完整故障归档、配置及既有 Team 身份核验。检查选定 MySQL 数据库的全部队列和 ACTIVE claims（含过期），完整 Console Operations；不创建任何数据库/队列表，不截断清单。
- QUEUED/RUNNING Operations、READY/RETRY_SCHEDULED/LEASED/RUNNING WorkItems 和 ACTIVE claims 拒绝；等待人工/依赖可保留并明确计数。
- 精确计划及明确本机确认、执行时重新核查；事实漂移、损坏、未知输入 fail closed。原 marker 保留，仅追加完成回执。
- 首次普通 Host 写入前重新检查队列与配置并封存 admission；之后正常重启不被维护时的旧队列清单限制。退出维护不审批或继续 K1。
- UI 提供入口、两步本机命令及离线说明；HTTP inspection 禁写边界不变。

允许路径：src/ai_software_engineer/web_console/{maintenance_completion.py,maintenance_queue.py,maintenance_lock.py,maintenance_guide.py,maintenance_names.py,fault_retirement.py,host.py,transport.py}；team_view/app.js/style.css；scripts/ase-console-{service.sh,lifecycle.py,maintenance.py}；Schema 生成器、相关 Schema/tests/docs/.trellis。
验证：相关 pytest、Node tests、Ruff、增量 mypy；不跑全量。
回滚点：bf3f3a8。保留全部故障归档、marker、完成记录；可显式 ASE_CONSOLE_MODE=inspection 启动，不删除历史或制造 READY。
存量数据：本轮不操作生产解除维护、不改 K1/SQL/审批；完成记录是独立工程授权，未知历史保持原样。
