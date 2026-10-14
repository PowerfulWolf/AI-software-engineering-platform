# 受控暂停后重启

## Goal / authorization

用户已明确要求完成受控暂停后重启。日常 restart 不再等待整个 Requirement/Operation 全部交付。
关闭新操作和新模型/角色/重试入口，给当前调用有限的完成窗口；实际拥有的本机执行会话超时后
受控停止，封存实际停止与合法草稿，完成队列/Operation 保存后才发布 READY 和替换服务。

## Acceptance

- [ ] 当前角色可完成并通过原 artifact 门禁，下一角色/重试不启动。
- [ ] 超过收尾窗口的 native/structured Codex 会话由真实拥有者停止，记录独立 service_pause 原因。
- [ ] Service pause 不制造超时/provider 错误、verdict、DONE、预算退款或放宽旧冻结权限。
- [ ] Task checkpoint/源码/worktree/历史审批保留，角色 wait 原子释放 Lease；缺停止或保存证明拒绝重启。
- [ ] 原 Requirement 可从干净角色边界继续；dirty Coder 通过精确的原生基线恢复计划接回。
- [ ] 无法取消的同步 HTTP 调用保持实际等待，不以后台线程遗弃冒充停止。
- [ ] 默认 restart、stop、信号和设置 apply 同用一套控制，重复请求不延长窗口，解除停止不撤销已封存暂停。
- [ ] 存量 K1 不改 SQL/旧 Artifact，升级后验证在线读取并使用原需求恢复入口。

## Paths / validation / rollback

允许路径：src/ai_software_engineer/{service_pause.py,agents/**,web_console/**,work_queue/**,
orchestration/**,domain/**,knowledge/**,manager/**,multi_directory/**,team_view/**,evidence/**,tools/**,recovery/**,execution.py,owned_processes.py}，schemas/**，
tests/**，scripts/*schema*.py，docs/{architecture/contracts.md,operations/controlled-service-restart.md}，
scripts/ase-console-service.sh，
.trellis/spec/core/** 和本 Task 目录。仅修改有调用链依据的文件；不引入数据库迁移或新的角色权限。

验证：独立 owned-process fixture + Console 生命周期、队列/恢复、Schema contracts、Ruff、strict mypy。
基线：4863eb49c038b4b271607ede314ffdad78ffc73b。回滚先受控停止，保留所有 additive pause 记录及兼容读取器。
