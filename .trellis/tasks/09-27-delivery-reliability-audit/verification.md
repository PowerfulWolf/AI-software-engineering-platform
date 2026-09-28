# 本轮验证与恢复交接

## 边界

所有命令在 ASE 当前工作区执行，模型使用 fixture；MySQL 只使用已有 ASE_TEST_MYSQL_DSN，
由仓库隔离守卫检查，每次仅一个 MySQL pytest 进程。浏览器连接 fixture HTTP，不连生产。
没有业务代码代写、业务 QA/Reviewer 判定、生产 SQL 改写、Continue、审批、重启、部署或 merge。

## 已执行结果（2026-09-27）

| 命令/范围 | 实际结果 |
| --- | --- |
| 初始全库 `pytest -q -m 'not mysql'` | 1885 passed, 7 skipped, 92 deselected |
| `tests/recovery/test_prerequisite_repair_mysql.py` | 8 passed；native/legacy/新 Host 组合到 DONE，无重复 Coder |
| `tests/product tests/design tests/planning tests/knowledge -m 'not mysql'` | 337 passed, 1 deselected |
| 第一轮修后离线全库 | 1899 passed, 7 skipped, 94 deselected |
| verifier 修改后离线全库 | 1906 passed, 7 skipped, 95 deselected |
| `tests/manager/test_verifier_worktrees.py` | 8 passed；同进程/重启、2 个候选、partial/dirty/drift、foreign Task |
| 第一轮 MySQL 全库 | 92 passed, 2 failed；1377.83s，D7 与旧测试预期，未隐藏失败 |
| `tests/recovery/test_native.py tests/manager/test_verifier_retry_mysql.py` | 11 passed；两个失败修正后通过，QA 驳回后生产 Host/队列完成新候选交付 |
| native 修复后离线全库 | 1906 passed, 7 skipped, 95 deselected；189.95s |
| 补 foreign Task 反例后离线 | 1907 passed, 7 skipped, 95 deselected；208.50s |
| 第二轮 MySQL（主动中断定位） | 26 passed, 8 failed；644.90s，新增 guard 误把验收 source Task 当 execution Task，已修；该运行不算通过 |
| Task 双身份修复后的 production_delivery + verifier_worktrees | 15 passed；含 source 接受、execution Task 冒用拒绝 |
| 双身份修复后的 prerequisite + verifier_retry_mysql | 9 passed；117.46s，完整修复/知识等待/重启/新候选链 |
| 最终离线全库 | 1909 passed, 7 skipped, 95 deselected；205.14s |
| 固定生产代码后的 MySQL 全量（fail-fast） | 41 passed, 1 failed；1186.07s，失败为共享测试 greeting 把执行序号当候选版本；生产代码未再修改 |
| 修复测试数据隔离后的 MySQL 补跑 | 58 passed, 74 deselected；109.15s；包含失败项、全部余下用例及 4 个受 fixture 调整影响的已过用例 |
| MySQL 逐项覆盖结论 | 41 + 58 - 4 重复 = 全部 95 项通过；生产代码在这两批之间未改变，只有测试数据隔离修正；不是最后单次全库全绿 |
| fixture 修正后的相关离线补测 | 25 passed, 3 deselected；7.93s |
| `node --test tests/team_view/*.test.cjs` | 49 passed |
| `node --test tests/team_view/browser/*.test.cjs` | 38 passed；实际 Chrome + fixture HTTP；复用现有 NODE_PATH，未安装依赖 |
| `uv run --offline ruff check .` | passed |
| `uv run --offline ruff format --check .` | 939 files already formatted |
| `uv run --offline mypy src tests` | 475 source files passed |
| `uv build --offline` | wheel + sdist succeeded |
| `git diff --check` | passed |

所有 Python 命令由 `uv run --offline` 执行。7 个跳过是 3 个显式真实 CLI、2 个桌面、2 个
本机工具链/沙箱 opt-in 测试，本轮未冒充执行；2 个依赖弃用 warning 单列保留，没有屏蔽。

## 本轮文件增量归属

- 恢复来源：multi_directory/production 的 approved_joint_context_sources 与 recovery/context 的调用点。
- 历史知识：knowledge/legacy_scope 新文件、knowledge/runtime 兼容调用，以及相关知识/真实修复测试。
- 范围：knowledge/context、skills、agents 的可见性规则和 source_scope/consultation/delivery_context 测试。
- Product：service 的调用后 checkpoint guard 与两个并发输入测试。
- verifier：manager/production_delivery 的 checkout/cache 身份、role_workspace 单角色 seam；新 real Git 与 MySQL 测试。
- native：recovery/native 的 work_budget_exhausted；test_native 的冻结策略断言。
- 测试维护：4 个旧测试文件类型修复、production_backend fixture 支持正确 supersedes；不同候选的
  greeting 仅在 verifier_retry_mysql 用例中注入，不能让共享样例按执行序号猜测候选内容。
- 规范与任务：相关 spec 的新增条目、verifier-worktree-lifecycle、docs/git-worktree、本任务与任务索引。

上述有些文件已有大量前期修改，不能把整个 `git diff HEAD` 当成本轮 patch，也不能整文件回滚。
本轮不改 wire schema/生产数据。回滚只撤各项增量，不重置用户工作区或删除运行历史。

MySQL 补跑命令（与前一批不并行；测试收集共 95 项）：

```sh
uv run --offline pytest -q -m mysql -x --tb=short --durations=12 \
  tests/manager/test_production_backend.py tests/manager/test_verifier_retry_mysql.py \
  tests/recovery/test_resume.py::test_resume_recovers_post_feedback_coder_workspace_before_old_candidate_verification \
  tests/recovery/test_resume.py::test_resume_verifies_failed_candidate_and_delivers_remediation \
  tests/recovery/test_resume.py::test_resume_accepts_verified_candidate_after_delivery_checkpoint_append \
  tests/recovery/test_resume.py::test_resume_recovers_admitted_coder_after_legacy_inconclusive_remediation \
  tests/store tests/team_view/test_live.py tests/test_mysql_test_isolation.py tests/work_queue
```

本轮生产代码已固定，最后一次调整只恢复共享 fixture 的原始默认行为，并将多候选数据限定到新测试。
此前失败记录仍保留；最终按逐项覆盖收齐结果，不把分批验证误写成最后单次全库全绿。

## 审查验收结论

AC1–AC7 的本轮源码、平台实现与隔离验证已完成，证据见 audit.md 和上表；6 类已证实平台缺陷、
旧类型检查/测试预期问题及本轮回归均已关闭。AC8 的规范与恢复清单已落盘。代码未提交/部署、
真实需求仍 operator hold；用户确认受控加载与恢复前不推进，不把本轮工程验证视为业务验收。

## 原需求恢复清单（尚未执行）

1. 全量质量门通过并审阅本轮增量后，用户确认恢复原需求；确认没有并发 Operation/Worker，才受控加载新代码。
2. 原 parent `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006` 保持 operator hold；
   candidate `9ac7c9ee830df548571db55ec5cf809e613467ba` 和历史 gap/resolution/审批均不改写。
3. 从正常 Manager Continue/恢复入口读取当前事实。已获准 gap 解答不重复批准，已消费的执行批准不重放。
   如候选、scope、来源或执行器能力改变，由 Manager 生成新的精确计划，走正常批准。
4. 只有“旧 baseline 已封存而正文漏入 snapshot”的狭窄情形使用 legacy 兼容；其他摘要变化继续拒绝。
   特别是角色范围收窄后的旧 snapshot，不允许静默迁移成新权限。
5. 环境、数据、桌面锁定由 Manager 协调；平台维护者不替业务 Coder 修改，也不自行填写 QA/Review。
6. ASE 独立 QA PASS + Reviewer APPROVE、相同候选、父需求整体验收到 DONE 才是业务交付完成；不自动 merge。

## 不能据此宣称的能力

真实模型质量、真实桌面 UI 验收、所有未知路径零 bug、全自动知识收集、通用 Agent 能力自扩展、独立进程 fleet。
现有显式学习闭环已验证；自动上游收集/Manager 集成保留在 09-25-team-evolution-audit，不混成环境问题。

## 恢复后的增量验证（2026-09-27，持续更新）

用户确认恢复后，正常 Continue 仍遇到原 scope guard；确认父需求与修复任务的两份规范正文
版本不同。此事实推翻了“上一轮 fixture 已覆盖真实全部组合”的推断，但不使旧 snapshot guard
失效。新增 successor profile 正文绑定、Manager 接纳后重开 runtime 两处修复，保留旧失败记录。
新 Git/MySQL case 首先复现 stale preparation，随后通过；真实历史输入只读重放也由失败转通过。
后续命令、操作及业务验收结果记录在
`../09-25-joint-approval-delivery/continuation-20260927-post-audit.md`。
