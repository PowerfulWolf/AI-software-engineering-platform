# T047–T049 续作交付记录（2026-09-19）

本次从现有 `/private/tmp/ase-t047-t049-20260918` 续作，分支 `codex/t047-t049-20260918`，
基线 `266cd2380e3186b9aeff9765abc5c5b0f1572060`。保留先前全部未提交实现，不从头重建。
代码仍在该 worktree，尚未 commit、合并到主目录或部署。主目录同期 AGENTS.md 与
`docs/development-workflow.md` 的其他改动保持原样。

## 完成范围

| 任务 | 交付结果 |
| --- | --- |
| T047 planner-agent-evolution | Manager 确定性复杂度分类、零模型简单计划、有界复杂工作图、验收/测试等级守恒、精确计划修订反馈、联合批准计划原样投影到各仓 |
| T048 active-knowledge-closure | 冻结作用域检索与证据、预算化 Context consultation、缺口批准与恢复、Learning 后续检索、实际 stage/delivery skill gates、调用 usage 与效果评测、标准人工干预归因、存量 artifact admission |
| T049 incremental-knowledge-indexing | 异步持久化导入、增量缓存、原子索引发布、失败重试与重启恢复、选择/替换/退休并发互斥、分作用域故障隔离、页面状态与重试 |

T048 queue wait adapter 已通过真实 MySQL owner fence/lease release 测试；当前 `ase request`
仍使用已有串行 RuntimeSession，没有迁移成逐角色 WorkQueue Worker。可选 Curator Agent 未实现。
知识效果报告来自实际检索驱动的确定性 fixture，不代表真实模型质量测量。

## 独立验证

- T047 独立 Reviewer 复查后无剩余发现；此前定向测试 70 passed，4 个 MySQL fixture 当时跳过。
  本轮真实 MySQL 联合交付和下面的规划回归继续验证最终装配。
- T048 独立 QA 四份测试 34 passed，涵盖真实检索评测、Learning 发布、持久化恢复、人工 ADR、
  候选更换与升级前 artifact 恢复；记录在任务目录 `qa.md`。
- T048/T049 独立 Review 的全部发现已闭合；最终定向 64 passed，4 个当时无 DSN 的测试跳过。
  T049 独立索引/管理测试 42 passed。历史 findings、修复复查及文件摘要保留在 T048 `review.md`。

## 本轮质量门

使用主仓已存在的 `.venv`，`PYTHONPATH=src` 指向本 worktree。下表的 `python`/`ruff`/`mypy`
均为 `/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/` 中的工具。

| 命令或范围 | 结果 |
| --- | --- |
| `python -m pytest -q -m 'not mysql'` | 1464 passed，60 deselected；2 个第三方弃用警告 |
| 最终知识/规划/交付定向回归：`tests/knowledge tests/planning tests/e2e/test_planned_delivery.py tests/manager/test_joint_planner_feedback.py tests/manager/test_production_delivery.py --ignore=tests/knowledge/test_queue_mysql.py` | 246 passed |
| 最终 stage 与 joint recovery 边界：`tests/knowledge/test_stages.py tests/planning/test_joint_gate.py tests/manager/test_joint_planner_feedback.py tests/manager/test_single_repository_acceptance.py` | 37 passed |
| Schema、联合契约与核心 contracts | 117 passed |
| 带隔离 DSN 的 `tests/knowledge/test_queue_mysql.py tests/manager/test_mysql_dispatch_authority.py tests/manager/test_production_backend.py tests/e2e/test_joint_delivery.py` | 19 passed（98.44 秒） |
| `ruff check .` / `ruff format --check .` | 通过；748 个文件格式检查通过 |
| `mypy src tests` | 410 个源文件通过 |
| `node --test tests/team_view/ui.test.cjs` | 6 passed |
| `git diff --check` / 联合任务 allowlist | 通过；无越界文件 |

MySQL 使用本次专用数据库 `ase_t047_t049_20260919_test`，未使用或修改业务数据库。
必要的测试账户授权只作用该测试库。测试脚本只在进程环境传 DSN，后续输出统一脱敏。
修正了既有 MySQL fixture 中“completed/released”消息断言和单 verifier reservation，
使其符合已存在的 QA+Reviewer 两阶段契约；未放宽生产校验。

验证限制：尝试完整 `-m mysql` 时，在一个既有的
`test_resume_discovers_approves_and_attaches_pre_candidate_coder_recovery` 上出现异常长耗时，
主动中断。随后单测的 30/90 秒诊断均定位到原有 RecoveryCurrentStateValidator 的重复 Git
capture/authorization 校验链；隔离网络后仍出现，尚未归因成确定的产品缺陷。因此不声称完整
60 项 MySQL 集合全部通过。直接覆盖本轮三项的上述 19 项已全部完成，T048 的新旧 Context/
候选/GAP 恢复另有独立 SQLite/文件 fixture 验证。诊断未改生产恢复逻辑或业务数据。

## 存量数据处置

没有修改任何生产 Requirement、Task、Operation、角色 verdict、审批或知识选择。

- 旧计划/Context/冻结知识保持原摘要。新版本计划使用更严格的精确前驱和测试覆盖校验。
- 升级后首次运行对已有非 NEW Task 封存一次性 admission，只允许已存在的 exact legacy artifacts
  使用原生 QA/Review 恢复路径，不改旧 Context、不补造咨询证据。新 artifacts 强制知识 gate。
- 知识缺口由 exact 人工 Resolution 批准后执行 `ase request resume <requirement_id>`。首次恢复使用
  原候选；后续候选复用通过首个恢复摘要串联。人工干预保留在 Evaluation 中。
- 旧索引由正常 tick 从 verified READY caches 与当前 selection 修复指针。若此前竞态覆盖真实选择，
  用户在对应 Team/Project 页面重新保存意图；平台不猜测授权范围。
- 已终态的失败任务仍遵守现有显式恢复计划/批准，不直接改库复位。

逐步 API 操作、返回值、当前队列边界见 `docs/planning-knowledge-operations.md`。

## 风险与回滚

真实模型质量、全部历史 MySQL 恢复用例及部署后的用户界面人工验收未在本次宣称完成。
当前交付是已验证的未提交工作区成果，主目录尚无这些代码。

回滚前停止新工作及索引写入，恢复本轮代码与 Schema；保留外置 artifacts、Context、admission、
Gap/Resolution、index 数据库、原始文档和所有批准历史。可以回到 baseline 检索 adapter；
不要删除历史或重置状态来回滚。没有自动 merge 或生产部署需要撤销。
