# 实施与验证

- 已复现真实请求拒绝：`operation_d042a07975dc4d7769c2a4829b0e6a7f`。新增helper定向测试先因入口缺失失败。
- `accepted_scope_progress` 从最新接纳事件校验sealed progress、完整fallback route和Context；
  `NativeRecoverySource` 保留真正最后失败Run/Context，只更新scope evidence查找。
- 独立Reviewer/QA发现并已修复跨revision兼容问题：早期progress已被candidate推进淘汰时
  返回无scope evidence，不阻断普通post-feedback恢复。当前revision证据损坏仍拒绝。
- `pytest -q tests/recovery/test_scope_progress_history.py tests/recovery/test_progress_source.py
  tests/recovery/test_scope.py`：37 passed /6.59s。覆盖latest-only、绑定、缺失、合法及非法
  fallback链、三类symlink、跨revision。
- `pytest -q 'tests/recovery/test_native.py::test_budget_exhausted_coder_progress_is_a_recoverable_native_source[False-True]' --tb=short`：
  1 passed /149.48s。真实Git/MySQL、离线角色：已接纳progress后执行失败，scope→plan双审批，
  capture.patch包含后轮新字节，新Coder→QA→Review→DONE，旧Task/events不变。
- 新场景使用专用OfflineRunner.seed_text参数核对真实不同seed，原fixtures默认值不变。
- 五个相关Python文件Ruff/format/Mypy通过，git diff --check通过。无全量测试。
- 独立Reviewer最终无阻断项；独立QA确认crossrevision finding关闭，复跑新增17项快测
  全过（0.58s），未并发MySQL或修改文件。
- 原生fixture最初混入普通单仓主干前进时触发该入口的preparation drift；该扩展不属于本修复。
  新增fixture收窄为timeout+scope完整恢复，主干前进复用既有joint main_advances验证；真实K1是joint。
- 生产只读预检正确返回失败run `run_0b7938195c2f47ea9fbacc77da3f231b` 和scope progress
  `art_coder_b10b7bc4c0e81300c69104d2ec890f8a`，没有修改Task或生产SQL。

## 存量处置与回滚

用户明确要求新基线继续；旧Task已终态、所有WorkItem CLOSED、无活动Operation后，业务
main由`acc5f37`安全快进到已推送`15de91c`。旧Coder worktree与19条dirty paths保留。
修复加载后通过同一scope request产生新精确审批，继而生成绑定当前目标基线的恢复计划。
完整旧补丁冲突时必须另行批准coder_reapply，由原生Coder适配；不得手改业务实现。
回滚只回退代码并于无活动执行时重启，保留所有旧Task、approval、capture和journal。
