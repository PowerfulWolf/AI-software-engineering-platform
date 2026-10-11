# 知识准备本地窗口的同任务受控续跑

## 问题与目标

已完成真实 native 停止及完整 journal 封存的知识准备 local_execution_limit，目前只能进入泛化故障等待，不能在原 Task 安全扩大下一次知识准备窗口。实现精确、可审计、有限的工程等待决定；保持 Task、source、worktree、串行角色及 QA/Review 独立性。

## 范围与权限

新增 typed knowledge-local-limit failure、RETRY_KNOWLEDGE_PREPARATION resolution/evidence、生产只读 collector、MySQL 原子等待消费及已消费决定的冻结窗口 resolver。不修改 team_view 或 baseline.py，不操作生产、审批、重启或提交。复用 Task 冻结 DELIVERY_WAIT_RESOLUTION 工程授权；旧 Task 无该授权只能由真实工程主体批准 exact proof，绝不追溯添加 policy。

shared legacy scope resolver 让 runtime、collector 与由 root 维护的 history 复用同一可验证兼容；requirement_id 保留历史知识归属，delivery_requirement_id 显式记录 native 父交付身份，不能凭 Task 命名放宽父归属。local-limit索引只定位已封存事实，缺索引写失败不能重启原调用。

## 验收

- 只有 FAILED/TIMEOUT/local_execution_limit、真实 native STOP、全部 route completion 独立可重读且主角色尚未开始的调用可继续；pending、owner loss、记录漂移、错 claim/scope/source、已开始主角色都拒绝。
- 原始 intent timeout 冻结 initial；最多两次扩窗，每次乘二，max=min(initial*4,86400)。后续窗口只来自已消费 WAIT_RESOLVED 链；当前热配置不可替换。
- 消费共享冻结 work 额度，不消费或退款 provider transient；新 work item、真实 claim、Run/Context，保留同 Task、source 和 worktree。精确重放不重复扣额度。
- 窗口封顶或工作额度耗尽时不提供必败动作；旧记录 wire/digest 可读，原历史不修改。
- 旧 continuation QA/Reviewer 的完整 gap/snapshot 可在正确 native 父需求继续；错 scope/source/snapshot、漂移独立 gap key 或缺 snapshot 拒绝。None 的双身份字段不改变旧 digest。

## 验证与回滚

只运行相关 domain、knowledge、retry、delivery-wait、queue 增量测试及局部 Ruff/mypy。需要 MySQL 的验证仅使用 ASE_TEST_MYSQL_DSN 指定测试库。回滚保留新增 typed 记录 reader；不删历史，不重置 Task，不重建需求。
