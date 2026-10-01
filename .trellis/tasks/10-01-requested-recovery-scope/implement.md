# 实施

- 独立 QA 已确认无现成入口；当前业务 attempt3 不受本地开发影响。
- 先补模型/路径契约与拒绝测试，再接Console/native recovery；只跑增量测试。

## 增量与独立检查

- requested scope/legacy model/Console选择集15 passed，新增带request和旧无request模型Schema验证2 passed。
- Node delivery-status + UI 14 passed，包括scope request原样回传。
- 原生预算耗尽恢复[False]：1 passed /109.48s，覆盖scope→plan双审批、新Task→QA→Review→DONE、旧Task/events不变。
- Reviewer要求加强接纳事件证明：新增has_accepted_progress检查route task/run/context/revision、精确IMPLEMENTING→CONTINUE_REQUIRED/reason/attempt/artifact。只有BLOCKED引用不能通过，增量反向10 passed。Reviewer复核无剩余问题。
- 独立QA：[True]原生恢复1 passed /136.58s；scope/progress/model/Console 33 passed；Node14 passed。测试库已释放。测试fixture enum构造warning已用正式model_validate移除。
- 相关源文件Ruff/format/Mypy通过，git diff --check通过。按check/check-cross-layer核对Console→Resume→Entry→scope→current facts→新Task及scope UI roundtrip。未运行全量测试。
- 尚未加载服务：真实K1 attempt3仍活动，等待自然结束；生产SQL/业务worktree未改。
- 独立QA提出两处低级wire不一致：Console scope request的approval kind限制、supplement request/requested_files成对约束。已同步generator/schema及四类删除/null反向测试；定向4 passed，typed与JSON Schema均拒绝。未涉及运行时权限放宽。
- 独立QA最终复核：上述两个low findings关闭；额外0/9 requested_files边界两种validator均拒绝，Schema自身有效；定向3 passed。独立Reviewer无剩余问题。
- 06:31Z真实K1第三份progress art_coder_4375c6530f603c25a701a30048d5b5df已接纳，自动进入attempt4。只读冻结Context显示max_work_attempts=10/max_attempts=40，不能假定默认3轮耗尽；不修改预算或打断活跃执行。当前scope修复状态verified_pending_activation。
