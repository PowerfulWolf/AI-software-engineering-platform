# 实施顺序

- [x] 用户批准创建，随后明确批准全阶段审查、修复和架构调整；inline 执行。
- [x] 保留既有 dirty worktree 和真实需求检查点；不提交新的生产操作。
- [x] 建立 PRD、设计、全生命周期审查表和测试入口。
- [x] S1：运行全库离线基线与静态检查；逐阶段审查输入/输出/恢复，区分确认缺陷和调查项。
- [x] S2：真实形态 fixture（原生文档 + 旧 gap + 修复 + 重启），复现首次/恢复上下文分叉；统一来源投影。
- [x] S3：历史检索快照与当前角色上下文分离，补正反兼容测试；保留原审批和失败历史。
- [x] S4：审查全部 14 阶段；修复知识权限、Product 窗口、verifier 生命周期和 native 预算恢复问题。
- [x] S5：隔离 MySQL 串行分批覆盖全部 95 项、完整离线和前端回归、规范沉淀、明确存量恢复步骤。
- [x] S6：审查项全部有结论，已确认阻断/越权/证据完整性缺陷关闭，恢复交付清单已形成。

## 验证命令

从 ASE 仓库执行，不使用真实业务仓库或生产 DSN：

```sh
uv run --offline pytest -q -m 'not mysql'
uv run --offline pytest -q tests/knowledge/test_legacy_continuation_scope.py
uv run --offline pytest -q tests/recovery/test_prerequisite_repair_mysql.py
uv run --offline pytest -q -m mysql --tb=short --durations=12
uv run --offline ruff check .
uv run --offline ruff format --check .
uv run --offline mypy src tests
node --test tests/team_view/*.test.cjs
git diff --check
```

MySQL 测试仅在已有 `ASE_TEST_MYSQL_DSN` 通过隔离库守卫时运行、不得并行。缺少时记录未验证，
不能换成生产 DSN。真实模型调用、桌面驱动、环境安装不属于这轮离线审查自动权限。
测试数字仅作执行记录，不替代逐阶段结论；未完成项目保持未完成。

## 高风险必测组合

1. 空知识与原生/Team/Project 知识；首次执行与新 Host 重开；单仓与联合需求。
2. QA/Reviewer gap、精确解答、新候选；旧 Task scope/旧说明摘要，不改历史事实。
3. 审批前后/receipt 后/checkpoint 前中断、重复请求、过期 digest。
4. claim 过期、续租失败、知识等待释放、旧 worker 后续写入拒绝。
5. QA FAIL/INCONCLUSIVE/未执行与 PASS 的区别；独立 Reviewer 和相同 candidate 门禁。
6. 学习观察 → 人工决策 → 发布 → 页面读取 → 新需求复用；原需求冻结与权限不变。

当前结果、发现与责任边界见 audit.md；命令记录、增量归属和恢复清单见 verification.md。
本轮审查与隔离验证已完成；保持 verified_delivery_held 等待受控加载/真实验收，不执行原业务恢复或自动归档/提交。
