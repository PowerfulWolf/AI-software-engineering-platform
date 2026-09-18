# T050 验证与操作交接

## 修复结果

候选恢复计划从终态 `qa_passed` 事件绑定已封存的 QA artifact ID/SHA-256。
同一 Task、candidate、implementation 和验收标准一致时，仅创建新的 Reviewer 调用；
completion 保留原 QA，且不生成本计划的 QA invocation。普通 QA → Reviewer 路径保留。

Reviewer REJECT 后的 remediation lineage 同样支持复用 QA，避免因缺少本计划 QA invocation
而无法继续。历史 QA producer 以封存报告验证，不错误绑定到新计划重新分配的 QA 成员。
Web 审批摘要显示“复用已通过 QA 并只重新执行 Reviewer”，列出复用 QA 和新的 Reviewer 模型。

## 自动验证

- `.venv/bin/pytest -q tests/recovery tests/manager/test_verification_reservation.py tests/web_console/test_manager.py`
  → **143 passed, 16 skipped**。跳过项需要 `ASE_TEST_MYSQL_DSN`，本次未配置。
- 最后将两处测试 fixture 改为显式 typed model 后，复跑
  `.venv/bin/pytest -q tests/recovery/test_candidate_verification.py tests/web_console/test_manager.py`
  → **29 passed**。
- `task.json` 所列 Ruff check、format check 均通过。
- `task.json` 所列 Mypy 检查通过（29 个源码/测试文件）。
- candidate-verification Schema 的 plan、authorization、Reviewer invocation、completion 正例
  在 admission 测试中校验通过；`git diff --check` 通过。
- Reviewer-only REJECT 延续用例先复现缺失 QA invocation 的失败，再验证修复通过。
- QA 新分配成员用例先复现历史 producer 被错误拒绝，再验证修复通过。

上述为开发回归检查，不是对真实需求生成 QA/Review verdict。本次未调用真实模型，也未运行
真实 MySQL 集成验证。资源 reservation 仍按既有契约保留 QA/Reviewer 两个 phase，但复用路径
没有 QA provider 调用；QA 容量不足仍可能影响计划分配。

## 存量数据处置

无需改库。原 Task、事件、QA PASS、失败 Reviewer run 和旧审批计划均保留为不可变历史。
本会话前序定位的“增加配置应用按钮”候选为 `d337b6bf6b42788876b9296896081ae92030e0f3`，
QA artifact 为 `art_qa_0fb53b11d5215d7536703ab4e1ebf331`。
旧未批准计划 `60b1dd5288fcf515c23c00143e370da864e1a6cf7c87ad6b471aa07c5f96c28e`
缺少新的 QA binding；再次继续时由平台检查当前事实并生成新计划，不能修改旧计划。

用户操作：

1. 使用当前平台的同一 `ASE_CONFIG` 执行 `./scripts/ase-console-service.sh restart`。
2. 刷新 Web Console，打开原需求，点击一次“继续交付”并等待操作完成。
3. 在阻塞信息中检查新摘要“复用已通过 QA 并只重新执行 Reviewer”，确认 Reviewer 模型配置。
4. 点击该新计划的“批准并继续”，由平台启动 Reviewer。
5. 若 Reviewer APPROVE，继续正常交付/联合验收；若 REJECT，现有流程按 findings 进入 Coder 修复，
   新 candidate 仍须正常 QA 和 Review。若 provider 再次失败，保留运行记录并反馈该次错误。

若仍显示旧“批准独立 QA 与 Reviewer 验证”摘要，先确认服务加载了更新代码且新“继续交付”
Operation 已完成，再检查该 Operation，避免批准旧摘要。

## 回滚

仅回退 T050 对代码和 Schema 的变更并重启，保留工作区其他修改和全部 sidecar/MySQL 历史。
旧版本不能读取带 `accepted_qa` 的新格式计划；恢复旧版执行必须重新生成兼容计划并按平台流程
批准，不得删除新计划或把其审批移用到旧计划。

## 16:09 平台验证反馈：模型路由快照过期

新计划 `6b1bda3b0ff3719ae361580c835860ffa1ad4f2d6fd77f4e5eca83c66ff6a9ea`
已经正确引用原 QA PASS，只创建了 Reviewer invocation
`run_71644d7695ac4a819946ceda03613934`，没有新的 QA invocation 或 provider route attempt。
它从旧 Task workforce snapshot 选择 `gpt-6-astra@medium`，而重启后的 Reviewer 配置为
`gpt-5.6-sol@high → gpt-5.6-terra@high`。实际 adapter 离线重放报
`ProductionConfigError: dispatch route is unavailable or ambiguous: codex/gpt-6-astra@medium`。
只读查询 MySQL 得到的 abandonment SHA 为
`4e9a87d057e019bec48da12bc5b6871d089d91448ebb4dc37bb5250e9470f063`，与该计划的
`ProductionConfigError` 摘要完全一致；completion 为空，reservation 已释放。

本次修复让 proposal 和 fenced execution 都使用当前生产 ModelPolicy，保留旧 snapshot
的 Agent、assignment、lease 和 digest。审批摘要绑定完整当前策略，角色路由选择或顺序变化
也要求新计划。既有 Task、QA/Review、计划、审批和失败记录均未修改。

### 本次定向验证

- 新路由测试先复现同一 `ProductionConfigError`，以及角色路由变化未使审批摘要变化的问题；
  修复后包含配置变化/不变、路由顺序、未知策略和容量占用的 6 个用例通过。
- `.venv/bin/pytest -q tests/recovery/test_verification_routing.py tests/recovery/test_candidate_verification.py tests/recovery/test_verification_admission.py tests/recovery/test_resume.py tests/recovery/test_delivery_continuation.py tests/manager/test_verification_reservation.py tests/web_console/test_manager.py`
  → **59 passed, 7 skipped**；跳过项仍因缺少 `ASE_TEST_MYSQL_DSN`。
- 本次两个 Python 文件 Ruff check/format、Mypy 与 `git diff --check` 通过。
- 使用真实已保存计划和当前配置进行离线路由检查：旧审批判定过期，新 allocation 选中
  `codex/gpt-5.6-sol@high`，adapter 路由为 sol → terra；0 次 provider 调用。
  这不是线上 Reviewer 执行结果，真实验证仍由用户在平台操作。

### 存量数据处置与下一步

无需改库。失败计划已消费且释放，保留历史；原 candidate 和 QA PASS 仍有效。
页面 `Continue the delivery to create and approve a fresh verification plan.` 是此状态的正确
恢复指引，但这次触发中断的模型策略错配是程序缺陷，直接反复批准会重复失败。

1. 使用同一 `ASE_CONFIG=/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json`
   重启 Console，使修复和当前模型配置进入同一个 Host。
2. 打开“增加配置应用按钮”，点击一次“继续交付”，等待新计划生成。
3. 核对“复用已通过 QA 并只重新执行 Reviewer”以及 Reviewer 模型，再点“批准并继续”。
   当前角色配置会选 sol；若要使用 GPT-6，先在设置中把 Reviewer 主路由改为 GPT-6，
   应用/重启后重新生成计划。全局启用 GPT-6 不等于 Reviewer 已选择它。
4. 旧计划/旧调用不重放，不重跑已封存 QA。后续新的 candidate 仍正常接受 QA/Review。

仅回滚本次路由修复时，恢复修改前的 `verification_entry.py` 相关 hunks 并重启；保留历史。
已知旧版本会再次遇到策略错配，因此回滚后暂停此候选的重复审批，等待兼容修复。

## 后续平台验收：Reviewer 已通过

用户后续操作生成 completion
`5490d892d999efee95b2eb8d093e66c245908b23e3ba45a629a439abe45a1b51`，复用 QA PASS，
Reviewer run `run_120692f786034f94a9da7111e5b266b5` 产出 APPROVE。
原生 sequence 55 已 DONE，candidate 为 `d337b6bf6b42788876b9296896081ae92030e0f3`。
父需求仍在 DELIVERING 的问题独立记录为 T051；此时不应重复本页前面的验证计划审批步骤，
应按 [平台操作闭环](../../../docs/operator-feedback-loop.md) 的最新“子仓库完成”步骤继续联合集成。
