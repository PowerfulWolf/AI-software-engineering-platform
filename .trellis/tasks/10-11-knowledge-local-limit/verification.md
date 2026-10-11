# Incremental Verification · 2026-10-11

只运行相关增量测试；未运行全量，未操作生产、审批、重启或提交。MySQL 使用
`ASE_TEST_MYSQL_DSN` 的隔离测试库，经现有 safety hooks 校验并串行 reset，无 skip。

## 核心验证

- `pytest -q tests/work_queue/test_knowledge_preparation_retry_mysql.py tests/work_queue/test_wait_resolution_mysql.py --tb=short`
  — 32 passed in 34.12s（知识续跑 12 例 + 既有精确等待消费 20 例）。
- 新增双 Requirement scope 后，知识续跑原 12 例再次全部通过；新增 legacy QA/Reviewer
  2 例首次仅 fixture 缺 `timeout_seconds` keyword 失败。修正后仅重跑新增例：
  `pytest -q tests/work_queue/test_knowledge_preparation_retry_mysql.py -k legacy_verifier_knowledge_scope --tb=short`
  — 2 passed, 12 deselected in 4.53s。最终该文件所有 14 例均已有通过结果。
- `pytest -q tests/knowledge/test_delivery_context.py tests/knowledge/test_invocation_native.py --tb=short`
  — 54 passed in 13.46s，覆盖 actual claim timeout override、七角色 typed native failure/replay。
- 新增索引写失败反例后仅执行
  `pytest -q tests/knowledge/test_invocation_native.py -k local_limit_index_failure --tb=short`
  — 1 passed, 34 deselected in 1.61s；原 outcome/独立 STOP 保留，同 Run 只补索引不重启。
- `pytest -q tests/knowledge/test_delivery_requirement_scope.py tests/knowledge/test_legacy_continuation_scope.py tests/knowledge/test_delivery_context.py --tb=short`
  — 40 passed in 1.88s（shared resolver 14 例 + 原 legacy 6 例 + context 20 例）。
- 先前核心域/manager/retry相关增量
  `pytest -q tests/manager/test_delivery_wait.py tests/orchestration/test_retry.py tests/domain/test_knowledge_preparation_retry_schema.py`
  — 83 passed。双身份的后续 Schema 5 例、UI/history 与总体回归由对应独立代理补充验证，
  不把其结果冒记为本代理运行结果。

## 质量门

15 个 owned Python source/test 文件执行 Ruff check、format --check 与严格 mypy：全通过；
`git diff --check` 通过。mypy 检出 production backend timeout 注入用了不存在的 `_work_queue`，
已修为当前真实领取队列 `queue.knowledge_timeout`，最终类型检查无错误。

独立 review 发现 legacy knowledge scope 与 native parent 不一致的兼容缺口，已通过 shared
resolver、双身份 evidence 和真实 QA/Reviewer MySQL 续跑修复。没有变更数据库 Schema，
没有修改生产 Task/审批/历史。

## 交付限制、存量处置与回滚

只允许完整 native STOP/local-limit journal、精确归属、main 尚未开始、有剩余冻结工作额度
的非终态 Task 续跑；未知中断不在本补丁授权范围。最多两次扩窗，provider 后继不刷新额度。

装载版本须等待当前受控执行结束，通过公开“让平台处理知识准备”入口核验并消费；旧无
冻结 capability 仍需 exact 工程主体决定。缺旧事实不补造，不改库，不重新建需求。
回滚保留新 typed records 的 reader/Schema；已经消费的新决定不能交给不认识该类型的旧写端。

完整可执行契约见 `.trellis/spec/core/knowledge-local-limit.md`。
