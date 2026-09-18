# T050 — 复用已封存 QA PASS 并仅恢复 Reviewer

## Goal

当候选代码已经取得可信、完整的 QA PASS，而 Reviewer 因额度、provider 或进程中断未产生 verdict 时，
后续候选验证计划复用该 QA artifact，仅启动新的独立 Reviewer run。

## Requirements

- 只复用终态 Task 的 `QA → REVIEW` 事件明确引用、与当前 candidate 和 implementation 精确一致的
  sealed QA PASS；
- 新 verification plan 必须绑定 QA artifact ID 与 digest，current-fact 检查发现任何漂移立即拒绝；
- Reviewer request 继续把该 QA report 作为直接 parent；Reviewer 必须与 Coder、QA 保持独立；
- reviewer-only completion 记录复用的 QA fact 和新的 Reviewer invocation，不伪造本 plan 的 QA invocation；
- 没有合格 QA PASS 时保留现有 QA → Reviewer 路径；candidate、QA 或 lineage 变化时不得复用；
- 已生成但未批准的旧 QA → Reviewer plan 保留历史；新代码应将其判为 source drift，并生成新计划；
- 不改写现有 Task、StateEvent、artifact、Operation 或 verdict，不直接修数据库。

## Acceptance Criteria（代码与离线验证）

- [x] Reviewer provider failure后的新计划精确绑定原 QA PASS；
- [x] 执行该计划只调用 Reviewer，一次 QA 模型调用都不发生；
- [x] Reviewer context 包含原 plan、implementation 和 QA artifact，并生成以 QA 为 parent 的 review-report；
- [x] QA digest、candidate、event lineage、role identity 任一漂移时 provider 调用数为零；
- [x] 普通 candidate verification 仍按 QA → Reviewer 执行；
- [x] completion、schema、store 重放和 current-fact tests 覆盖复用与拒绝场景。

真实平台执行由用户继续操作验收；MySQL 集成用例的跳过范围及恢复步骤见 `verification.md`。

## Follow-up: verification routing after Settings restart

- Incident: plan `6b1bda3b…` reused QA correctly, but selected the historical Task snapshot's
  `gpt-6-astra@medium` while current Reviewer routes were `gpt-5.6-sol@high → gpt-5.6-terra@high`.
  The saved abandonment digest confirms `ProductionConfigError`, before provider execution.
- Scope: use current production ModelPolicy for new verifier allocations in both proposal and
  fenced execution; retain snapshot Agent identities, assignments, leases and digest.
- Approval must bind role route membership/order as well as enabled route metadata. Configuration
  drift requires a successor plan and user approval before any new provider invocation.
- Verify offline: stale snapshot to current adapter route selection, role-only policy drift,
  capacity refusal, existing reviewer-only admission and recovery regressions.
- No schema migration or production data edits; preserve consumed plan, invocation and release.
- Rollback: revert this routing follow-up and restart; retain records and stop retrying the affected
  plan until a compatible fix is deployed.

## Existing Data Disposition

现有 QA artifact、Reviewer 失败记录、terminal Task 和 Delivery checkpoint 均为有效不可变历史，无需改库。
当前未批准 plan 不删除；服务更新后再次“继续交付”时，平台依据新增 QA binding 生成新的 exact plan，
用户批准后只运行 Reviewer。
