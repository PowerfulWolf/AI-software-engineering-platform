# Validation

RED: added actual shipped refresh -> successful normal Console -> Console network failure -> valid
same-Team summary test. Before change: expected teamReadIssue=null, actual unavailable. Existing
summary protocol remained v0.1 while Console handler cleared the Team used by its validator.

GREEN (2026-10-12):
- `node --test tests/team_view/team-summary-reading.test.cjs tests/team_view/readiness.test.cjs tests/team_view/operation-capabilities.test.cjs tests/team_view/operation-summary-reading.test.cjs tests/team_view/artifact-feedback.test.cjs tests/team_view/recovery-progress-summary.test.cjs`: 148 PASS.
- `PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/team_view/test_nullable_wire_ui.py`: 1 PASS.
- No full suite, production HTTP/browser operations, service restart, database mutation or K1 action by this worker. Root owns isolated browser verification and independent review.

Read-only identity and protocols remain last verified facts; all current delivery mutation authority is
revoked on metadata loss. Initial failure keeps existing legacy read-only behavior. Exact Team,
checkpoint, detail-source checks remain unchanged. Explicit 404 clears scopes; explicit valid
version or Team change invalidates old bodies. Unknown explicit Team protocol fails metadata
validation instead of silently falling back. Tests include same-Team body retention, no POST, no
full Operation history fallback, metadata/header/body races and old summary publication refusal.

Existing data: no migration or historical facts change. Final deployment must keep maintenance-only
marker and K1 paused. Rollback is client asset restore plus reload. Production historical failure
root cause is not proven solely by this isolated reproduction.

## Independent review and real browser observation

Research reviewer independently ran summary + Operation summary + capabilities (65 PASS),
confirmed the original minimal reproduction now GREEN, and found no blocking correctness issue.

Root used Cua real browser against wholly fictitious localhost fixtures (9876/9877):
- main asset, normal metadata initially valid then `/console`503 with summary200: red “刷新失败，团队数据读取失败”.
- worktree asset, same sequence: “团队记录已更新；交付控制连接暂不可用，当前操作暂停”; requirements remain selectable and complete detail loads.
- same browser metadata recovers as inspection: current maintenance connected message.
- metadata503 again: banner says “上次确认服务处于维护仅查看模式；当前连接尚未确认”; complete detail remains readable.
No production data or mutation requests were used for this observation.

Limits: first load without any verified metadata and explicit 404 intentionally retain existing
legacy full reads. The no-full-history fallback guarantee covers transient failures after successful
summary negotiation. Fixture verification does not establish why a historical production request
failed, does not validate normal writer/Agent delivery, and does not authorize leaving inspection.
