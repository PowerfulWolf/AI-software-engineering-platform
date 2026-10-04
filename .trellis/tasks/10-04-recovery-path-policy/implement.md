# 执行记录

## 根因与修复

- 恢复 proposal 把缺失文件当成迁移文件，仅凭 basename 对齐。学习模块 audit.py 被错误映射到 knowledge/audit.py。删除自动重绑定，历史记录可读但不可再执行。
- 设计 affected_paths 被直接当作 Coder write policy，WorkspacePolicy 没有 Trellis 硬拒绝。生产编译剔除明确规范路径，typed write/candidate/progress 共用保护；macOS 大小写与 symlink alias 也拒绝。
- 旧规则误改不能靠删除现场或放宽权限恢复。专用只读历史 capture 保留完整补丁，精确 hash-bound quarantined_paths 强制 clean coder_reapply；当前事实、授权、Context、Schema 和审批展示同步。
- 恢复 Context 改为 provisional report/progress，与平台 CandidateCommitSkill 一致，不再要求 Coder 自行 commit。

## 增量验证

- 原始路径/权限回归：5 failed；复核大小写别名：4 failed/4 passed；修后相关回归通过。
- Git policy/capture、recovery models/authorization/scope/reapply：111 passed。
- Console Manager、candidate commit、Codex adapter、policy/reapply/quarantine：142 passed。
- authorization/models/scope/task record/Git seed：67 passed。
- 大小写补充后的 policy + protected recovery：42 passed。
- 新 context 后 protected recovery + reapply：8 passed。
- 真实隔离 Git/MySQL：新隔离恢复 + 普通 seed/reapply/legacy direct commit 4 passed；补充公共 Continue 接管后新隔离恢复 1 passed，断言同 Requirement DONE、原 ProductApproval 不变、无新增模型调用、旧 Task/events/worktree 保留。
- Node DOM harness：6 passed。
- 11 个生产变更文件标准 mypy 通过；新测试/Schema sync 的 3 文件 MYPYPATH=src、follow-imports=silent mypy 通过。
- Ruff、format、git diff --check、Schema regeneration 幂等通过。没有跑全量测试；数字来自不同增量执行，不能当作同一版本一次全量。

主要命令：

```sh
.venv/bin/pytest -q tests/recovery/test_protected_native.py
.venv/bin/pytest -q tests/recovery/test_execution.py::test_recovery_complete_native_delivery_and_preserve_failed_history
.venv/bin/pytest -q tests/recovery/test_protected_recovery.py tests/recovery/test_reapply.py tests/git/test_policy.py
.venv/bin/pytest -q tests/web_console/test_manager.py tests/git/test_candidate_commit.py tests/agents/test_codex_cli.py
.venv/bin/python scripts/sync-recovery-policy-schema.py
node --test tests/team_view/ui.test.cjs
```

## 独立复核与限制

/root/recovery_review 只读检查发现本机大小写 alias 可绕过保护；修复后独立探针确认写入拒绝，读取保持。其他 digest/current facts/clean seed/完整 patch/Console 无确认阻塞。按建议修正文档：typed 写入前拒绝与原生 CLI 后置候选门不等同。没有伪造 ASE 业务 QA/Review verdict，也没有做浏览器视觉验收。

## 存量数据处置

旧 d9ab670f… plan digest 与 sealed 文件 hash 重新核验，完整 23 文件现场仍在；未批准该错误计划。新代码拒绝执行旧计划，并通过正式 Continue 支持同 Requirement 的新精确隔离计划。无改库、删除补丁、预算退款或终态重置。

2026-10-04 用户要求修复后先整体思考再推进需求。本轮不提交新的实际 Coder 执行，K1 保持原 Requirement；方向评估与方案见 docs/architecture/2026-10-04-delivery-direction-review.md。平台修复可空闲部署，需求恢复执行有意暂停。

## 回滚

空闲时 revert 平台修复提交并重启 Host。生产历史、旧批准、Task/events、capture 与 worktree 不改；回滚不授权重新执行不安全旧计划。
