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
main由`acc5f37`经`15de91c`安全快进到已推送的本次修复`ed12f25`。旧Coder worktree
与19条dirty paths保留。2026-10-01 12:36Z确认原生新Coder在该基线上执行，无需改库。

- 修复已加载。相同scope request提案Operation `operation_7fb10648f1b31501cc3755e4f91dd616`
  成功，随后`operation_3232643e783bf67bc25357dc818ec28d`批准scope并提出恢复计划。
- scope精确绑定已接纳progress `art_coder_b10b7bc4c0e81300c69104d2ec890f8a`，
  SHA `e8b34e2b48574f849348ca6f3dc5c21602b9024b404c233340d9fd8fd0a0dd25`，
  新增路径仅`tests/contracts/test_json_schema_contracts.py`。
- scope审批SHA `2311e190c24d7a064369f53b21a3571e2b0fa483df5d27180b9de73c9917a256`。
- 恢复计划SHA `e35017a761b1037b5a1318e15125092262df883f0518b679d9f0dbad4cb7896f`，
  目标base `ed12f2550093ed3247775276eacf89339b68efb5`，输入`git_seed`。
- 完整旧补丁只读`git apply --check`成功，19个路径与文件SHA核对通过。canonical capture
  使用`--unified=0 --full-index`并去除hunk labels，不能与普通Git diff字节直接比较。
- 用户已授权代理精确审批。`operation_f46b65e723e1a0c1a59f01f506c5e5e2`消费新计划，
  创建`task_recovery_e35017a761b1037b5a1318e151250922`。新Coder worktree的实际HEAD
  为`ed12f25`，旧Task和worktree未重置。12:36Z队列attempt1/RUNNING、lease有效。
- Chrome实际页面显示“实现中”“Manager协调·处理中（继续交付）”，列表进行中1、阻塞中0，
  无pageerror；新Task状态IMPLEMENTING。旧Task的BLOCKED历史保留。
- 本任务完成指平台scope bug已修复并通过真实恢复入口验证；K1业务尚在执行，不能据此宣称
  QA/Review通过或需求交付完成。Python/MySQL验证能力缺口由独立Trellis任务继续记录。

回滚只回退平台代码并于无活动执行时重启，保留所有旧Task、approval、capture和journal。
较旧代码若不支持新计划契约，不得消费该计划。新Coder已运行，不能为回滚直接reset/rebase
其工作区；需要恢复时重新生成并批准精确计划。
