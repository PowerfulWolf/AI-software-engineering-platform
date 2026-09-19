# T049 — 建设知识导入后的异步解析与增量索引

## Goal

知识文档导入、替换、删除或选择变化后，由服务内确定性后台进程异步生成可检索、可校验、可增量更新的
知识索引，并原子发布新的可查询快照。索引服务只处理内容解析、分段、元数据和检索结构，不依赖模型，
不阻塞上传请求，也不把描述性知识自动升级为强制工程 Spec。

如后续需要语义归纳，可增加受限的 `Knowledge Curator Agent` 产生标签、摘要、知识卡片或 Spec proposal，
但它只提交候选 Artifact；任何工程 Spec 的创建和激活仍必须经过人工审阅与现有审批边界。

## Requirements

- 文档导入/替换/退休事务完成后发布 durable `KnowledgeIndexJob`，状态至少包含
  `QUEUED/PROCESSING/READY/FAILED/RETIRED`；上传接口不等待解析完成；
- 后台 `KnowledgeIndexer` 是确定性 application service，不是 AgentProfile，不调用模型，也不持有
  Requirement/Task 状态修改权限；
- 以 document ID、normalized SHA、parser version 和 index schema version 作为增量身份；内容未变时
  exact replay，变化时只重建受影响文档；
- 对 verified normalized Markdown 做标题树解析、有界 chunk、关键词/术语、scope、角色、Repository、
  来源 URI、document digest 和 section lineage 记录；
- 生成的是 `KnowledgeIndexManifest/Chunk` 等检索记录，不是可执行工程 `SpecDocument`；
- active index snapshot 原子切换；构建失败继续服务上一可信快照，并在管理页显示失败和重试入口；
- 文档替换后新快照不得返回旧文档，退休后立即从未来查询集合排除；历史 Requirement 仍可按绑定 digest
  重放旧知识；
- Team 与 Project 分别索引、分别授权；Project 查询可组合 Team snapshot，但不能读取其他 Project；
- T048 的 `search_knowledge/read_knowledge` 接口保持不变，只替换检索 adapter；
- 支持增量启动恢复、幂等 job、并发去重、有界批次、退避重试、可观测 backlog/lag/error；
- 第一阶段优先本地确定性全文索引（例如 MySQL Full-Text/BM25 等可替换 adapter），不把向量服务作为
  正确性依赖；后续 embedding 必须绑定模型、维度、版本和 chunk digest；
- 可选 Curator Agent 只能读取 verified chunks 并输出版本化 proposal；低置信、冲突或来源不足时产生
  KnowledgeGap，不能直接改索引原文、Knowledge Selection 或 Spec activation。

## Acceptance Criteria

- [x] 导入请求快速返回，后台 job 可观测并最终发布检索快照；
- [x] 新增、替换、退休和选择变化只处理受影响文档，服务重启后可继续；
- [x] 同一 document digest 不重复解析，parser/index 版本升级可显式重建；
- [x] 原子发布保证搜索永远读取完整旧快照或完整新快照，不读取半成品；
- [x] 构建失败不破坏上一快照，并暴露明确失败原因和安全重试；
- [x] Team/Project/Repository 范围隔离、retirement 和 historical replay 有契约测试；
- [x] T048 baseline adapter 与增量索引 adapter 通过同一检索 contract suite；
- [x] Curator Agent 若实现，只能产生人工可审阅 proposal，不能自动创建或激活工程 Spec；
- [x] 后台 worker、索引文件/表、Schemas、Spec、管理页状态和运维文档保持一致。

## Decision (ADR-lite)

**Context**：解析、分段和索引是可重复的基础设施工作，若交给模型 Agent，会引入成本、非确定性、额度
依赖和难以保证的增量一致性；但对知识做语义归纳或建议工程规范，可能需要模型判断。

**Decision**：采用“两层职责”。确定性后台 Indexer 负责权威索引和增量生命周期；可选 Curator Agent
只做语义增强并产出 proposal。索引记录与强制工程 Spec 分开，任何从知识到 Spec 的转换都进入现有
Learning/人工审批流程。

**Consequences**：导入和索引可稳定、低成本、可恢复地运行，同时保留未来语义增强空间；需要维护
job lifecycle、snapshot version、parser compatibility 和后台健康状态。

## Out of Scope

- 自动把导入文档转为 active engineering Spec；
- 让模型 Agent 负责后台轮询、锁、重试和索引一致性；
- 跨 Project 知识共享、互联网搜索或无界向量平台；
- 修改已冻结 Requirement 的知识快照。

## Technical Notes

- T049 依赖 T048 的 Knowledge Retrieval interface 与 contract tests；
- 复用现有 immutable document、selection、retirement 和 Learning approval 边界；
- 后台循环应参考 PersistentWorkQueue 的确定性 worker/lease 思路，但知识索引 job 不得混入交付
  `WorkItem`，避免把基础设施作业展示为团队 Agent 任务；
- 实施前补充 `.trellis/spec/core/team-workspace.md`、`python-runtime.md` 和 `web-console.md` 的可执行契约。

## Initial implementation evidence

- Implemented scope-owned durable source/job ingestion, fenced bounded worker, append-only job
  history, immutable digest-bound chunk cache and atomically published complete manifests.
- Web upload/replace now returns 202 with a job; management status/retry APIs and UI show queue,
  failures, lag and safe retry. Startup reconciles pre-existing verified documents without changing
  Requirement approvals or frozen snapshots. Optional Curator is intentionally not implemented.
- `tests/knowledge/test_index.py` exercises asynchronous upload, exact replay, restart/concurrency,
  backoff/retry history, replacement fences, retirement/historical replay, cache corruption, version
  upgrades and schema parity. Both retrieval adapters share the retrieval contract suite.
- Focused Python knowledge/Web transport/administration suite: 103 passed; UI Node suite: 6 passed.
  Coder verification is implementation evidence, not a QA or Review verdict.
- Existing data: no direct database repair is required. Startup scans existing immutable manifests
  into the new per-scope index, retaining existing selection and all prepared Requirement evidence.
  Failed uploads can be retried in the management page or replaced with corrected source bytes.
- Rollback: restore the previous code and baseline retrieval adapter; retain external index databases
  and immutable document files for history. Do not delete knowledge or rewrite approved contexts.

## Resume verification (2026-09-19)

- Continued the existing implementation; retained all prior files, job history and frozen snapshot
  interfaces. Fixed bounded claim memory, unrelated failed-import publication starvation, selection
  and retirement RMW races, and cross-scope worker starvation identified by independent inspection.
- Claims now read at most 32 eligible metadata records then only one chosen source BLOB. Replacement
  publishes verified old/new cache entries before live selection transfer; failed publication keeps
  the old document. Scope-local reentrant process locks cover worker and Console mutations.
- Added failing regressions first for failed-import replacement visibility, concurrent deselection
  and scope starvation (3 reproduced failures), then added Team/Project and concurrent retirement
  boundaries plus selected-replacement failure/publication-failure coverage.
- Focused index/retrieval/administration/documents/selection suite: 82 passed. Ruff check, format check and strict Mypy passed for
  the changed implementation/test files. These are Coder verification results, not role verdicts.
- Existing data: no production facts were edited. A normal fixed worker tick repairs a stale active
  pointer from verified READY caches and current selection; explicit user selection is needed only
  if an earlier race already overwrote their intended selection. Keep all jobs/documents/history.
- Rollback: restore code while retaining index databases and immutable sources; stop index writes
  before rolling back shared locking. Approved Requirements and historical knowledge remain frozen.

## 续作验收记录（2026-09-19）

本轮实现和任务相关验证已完成。完整测试结果、独立 QA/Review 引用、存量数据处置、
回滚及验证限制见 `docs/archive/2026-09-19-t047-t049-continuation.md`。实现已由源提交 `977a9c2` 合并到当前 `main`；
未执行推送或部署。
