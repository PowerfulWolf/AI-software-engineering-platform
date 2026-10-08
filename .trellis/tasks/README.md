# 工程任务索引

这里记录开发平台本身的工作，不是生产 TaskRepository 或平台 Operation 队列。
新增或维护记录时遵循 [任务记录格式](FORMAT.md)；workspace 的用途见
[workspace 说明](../workspace/README.md)。
状态取自各目录 task.json；completed 表示原工程记录的完成声明，具体测试和真实验收限制仍以报告为准。
旧目录路径保持稳定，按状态导航，避免迁移历史上下文里的路径引用。

维护时使用唯一 ID/目录名；补齐确切的基线、合并提交和验证证据。没有原始记录时使用
legacy_unknown，不推断已完成，不补造 QA/Review。独立报告原样归档，路径与哈希由 manifest 映射。
每次状态变化同步更新本索引。

<a id="active-tasks"></a>

## 当前工作与剩余验收

| 目录 | 状态 / 阶段 | 剩余事项 |
|---|---|---|
| [10-04-recovery-journal-read-reuse](10-04-recovery-journal-read-reuse/task.json) | in_progress / incremental_verified | 33 项 journal/联合契约及 2 项 native 恢复通过；当前 K1 模型运行结束后才能加载 |
| [10-04-pre-agent-restart-boundary](10-04-pre-agent-restart-boundary/task.json) | in_progress / incremental_verified | Git/queue/plan/lock 增量边界及终态基线漂移恢复通过；补充修复待推送和加载，K1 仍需真实独立 QA/Review |
| [10-03-execution-feedback-history](10-03-execution-feedback-history/task.json) | in_progress / implementation | 完成 QA/Review finding、Coder 反馈 lineage 与跨 successor Task 的完整执行记录；增量验证、推送与服务重载待完成 |
| [10-03-delivery-operability](10-03-delivery-operability/task.json) | in_progress / implementation | 修复 Delivery 自动 Project 定位、基线漂移诊断、阻塞中文细节和当前子交付状态展示；增量验证与真实 K1 恢复待完成 |
| [10-03-bounded-successor-branch-names](10-03-bounded-successor-branch-names/task.json) | completed / incremental_verified | 新 successor 从稳定业务根名生成；29 项语义分支测试、相关恢复选择测试、Ruff、mypy 通过；待提交推送并重载服务 |
| [10-03-active-child-over-stale-verification-blocker](10-03-active-child-over-stale-verification-blocker/task.json) | in_progress / implementation | 活动 Coder 恢复优先于旧 QA/Review 终态阻塞；增量回归、推送与服务重载待完成 |
| [10-04-team-view-route-ledger-cache](10-04-team-view-route-ledger-cache/task.json) | completed / incremental_verified | Team snapshot 在单次读取内复用模型路由记录；7 项 Team View 增量测试通过，待提交推送并重载服务 |
| [10-04-frozen-worktree-source-revision](10-04-frozen-worktree-source-revision/task.json) | in_progress / incremental_verified | 历史 linked worktree profile 使用 successor Task.base_ref 恢复；增量回归通过，待提交推送、重载 Console 并继续原交付 |
| [10-02-post-feedback-knowledge-recovery](10-02-post-feedback-knowledge-recovery/task.json) | completed / incremental_verified | exact unfinished知识咨询与clean候选恢复；真实Git/MySQL增量及独立QA/Review通过，待空闲加载并恢复K1 |
| [10-02-recovery-verdict-context](10-02-recovery-verdict-context/task.json) | completed / incremental_verified | 保留恢复前的 QA/Review finding；增量、Ruff、mypy与独立QA/Review通过；无活动角色时加载，K1继续原生验收 |
| [10-02-current-child-blocker-display](10-02-current-child-blocker-display/task.json) | completed / incremental_verified | 48项增量与独立QA/Review；静态展示更新，K1仍走原生交付 |
| [10-02-bounded-pytest-diagnostics](10-02-bounded-pytest-diagnostics/task.json) | completed / activated_pending_k1_receipt | 06441d5已加载；待新K1候选的受控验证receipt |
| [10-01-candidate-read-scope](10-01-candidate-read-scope/task.json) | completed / verified_pending_candidate_executor_activation | 完整候选差异与依赖、typed来源绑定及最终预算；78项增量与独立QA/Review，待受控MySQL前提后恢复同一K1候选 |
| [10-01-recovery-validation-cost](10-01-recovery-validation-cost/task.json) | planned / read_only_diagnosis_recorded | 已记录恢复分配前重复完整校验；待确定性计数回归及保留freshness门禁的优化 |
| [10-01-python-mysql-verification](10-01-python-mysql-verification/task.json) | completed / activated | 39389f4已加载；真实边界fixture通过，K1旧候选产生独立QA FAIL并回派修正 |
| [10-01-worker-lease-status-recovery](10-01-worker-lease-status-recovery/task.json) | in_progress / verification | 页面中断状态已验证；精确中断恢复、独立验收及 K1 真实交付继续推进 |
| [09-30-coder-preexecution-auth-recovery](09-30-coder-preexecution-auth-recovery/task.json) | in_progress / verification | 已接纳 Coder progress 的续跑知识失败恢复、CLI诊断分类；增量验证与 K1 继续交付 |
| [09-25-team-evolution-audit](09-25-team-evolution-audit/task.json) | in_progress / execute | 当前需求已交付；显式知识闭环与候选验证 Manager 协调已接通，下一步自动收集、上游学习生产者、通用能力扩展 |
| [09-23-codex-cli-proxy](09-23-codex-cli-proxy/task.json) | in_progress / ready_for_user_validation | operator API-key login and authenticated CLIProxyAPI smoke; then resume existing Requirement |
| [09-02-t033-delivery-reporter](09-02-t033-delivery-reporter/task.json) | planned / plan | 见原 PRD/任务记录 |
| [09-06-t044-explicit-delivery-recovery](09-06-t044-explicit-delivery-recovery/task.json) | in_progress / coder_reapply_offline_verified | new exact real target recovery plan and human approval；real Coder QA Reviewer validation |
| [09-15-requirement-source-baseline](09-15-requirement-source-baseline/task.json) | in_progress / ready_for_review | rerun the complete localhost socket and MySQL suite outside the restricted sandbox |
| [09-19-t046-worker-integration](09-19-t046-worker-integration/task.json) | in_progress / ready_for_user_validation | user-owned full regression；commit/integration and controlled production rollout when authorized |

<a id="legacy-tasks"></a>

## 历史状态待核实

下列目录原来没有 task.json；本次仅登记已有文档与未知状态。即使正文包含实现说明，
也需要核对原始合并和验收证据后再改变状态。

| 目录 | 原有材料 |
|---|---|
| [09-10-qa-environment-recovery](09-10-qa-environment-recovery/task.json) | [design.md](09-10-qa-environment-recovery/design.md)、[implement.md](09-10-qa-environment-recovery/implement.md)、[prd.md](09-10-qa-environment-recovery/prd.md) |
| [09-10-team-view-company-tabs](09-10-team-view-company-tabs/task.json) | [design.md](09-10-team-view-company-tabs/design.md)、[implement.md](09-10-team-view-company-tabs/implement.md)、[prd.md](09-10-team-view-company-tabs/prd.md) |
| [09-12-company-onboarding-feishu-settings](09-12-company-onboarding-feishu-settings/task.json) | [design.md](09-12-company-onboarding-feishu-settings/design.md)、[implement.md](09-12-company-onboarding-feishu-settings/implement.md)、[prd.md](09-12-company-onboarding-feishu-settings/prd.md) |
| [09-12-platform-root-default-integration](09-12-platform-root-default-integration/task.json) | [design.md](09-12-platform-root-default-integration/design.md)、[implement.md](09-12-platform-root-default-integration/implement.md)、[prd.md](09-12-platform-root-default-integration/prd.md) |
| [09-12-runtime-settings-status](09-12-runtime-settings-status/task.json) | [design.md](09-12-runtime-settings-status/design.md)、[implement.md](09-12-runtime-settings-status/implement.md)、[prd.md](09-12-runtime-settings-status/prd.md)、[verification.md](09-12-runtime-settings-status/verification.md) |
| [09-12-team-order-terminology-history](09-12-team-order-terminology-history/task.json) | [design.md](09-12-team-order-terminology-history/design.md)、[implement.md](09-12-team-order-terminology-history/implement.md)、[prd.md](09-12-team-order-terminology-history/prd.md) |
| [09-12-web-project-delivery-console](09-12-web-project-delivery-console/task.json) | [design.md](09-12-web-project-delivery-console/design.md)、[implement.md](09-12-web-project-delivery-console/implement.md)、[prd.md](09-12-web-project-delivery-console/prd.md) |
| [09-13-scoped-knowledge-management](09-13-scoped-knowledge-management/task.json) | [design.md](09-13-scoped-knowledge-management/design.md)、[implement.md](09-13-scoped-knowledge-management/implement.md)、[prd.md](09-13-scoped-knowledge-management/prd.md) |
| [09-18-t053-single-repository-acceptance](09-18-t053-single-repository-acceptance/task.json) | [design.md](09-18-t053-single-repository-acceptance/design.md)、[prd.md](09-18-t053-single-repository-acceptance/prd.md) |
| [09-20-requirement-git-error](09-20-requirement-git-error/task.json) | [fix.patch](09-20-requirement-git-error/fix.patch)、[implementation.md](09-20-requirement-git-error/implementation.md)、[prd.md](09-20-requirement-git-error/prd.md) |
| [09-21-model-diagnostics-knowledge-ui](09-21-model-diagnostics-knowledge-ui/task.json) | [prd.md](09-21-model-diagnostics-knowledge-ui/prd.md) |
| [09-21-product-failure-diagnostics](09-21-product-failure-diagnostics/task.json) | [prd.md](09-21-product-failure-diagnostics/prd.md) |
| [candidate-verification-recovery](candidate-verification-recovery/task.json) | [design.md](candidate-verification-recovery/design.md)、[implement.md](candidate-verification-recovery/implement.md)、[prd.md](candidate-verification-recovery/prd.md) |
| [universal-delivery-resume](universal-delivery-resume/task.json) | [design.md](universal-delivery-resume/design.md)、[implement.md](universal-delivery-resume/implement.md)、[prd.md](universal-delivery-resume/prd.md) |

## 已完成记录

原报告及历史路径保留。T047 曾重号，使用唯一目录名区分，详见 [当前路线](../../docs/roadmap/milestones.md)。

| 目录 | 任务 ID | 状态记录 |
|---|---|---|
| 10-08-console-operation-version | console-operation-version-20261008 | [completed](10-08-console-operation-version/task.json)：静态资源绑定服务启动、操作能力握手及中文受理错误；25 HTTP、119 CJS、11 browser 增量通过，待用户空闲加载 |
| 10-08-engineering-wait-user-path | engineering-wait-user-path-20261008 | [completed](10-08-engineering-wait-user-path/task.json)：平台处理中断入口、冻结策略自动处理与完整中文记录已增量验证；服务待用户空闲加载，旧无可信停止资料仍需平台维护 |
| 10-01-confirmation-execution-visibility | confirmation-execution-visibility-20261001 | [completed](10-01-confirmation-execution-visibility/task.json)：历史答复入口与角色心跳提示，44定向回归及独立检查通过，静态HTTP已加载 |
| 10-01-interrupted-coder-changes | interrupted-coder-changes-20261001 | [completed](10-01-interrupted-coder-changes/task.json)：9f00cf7 已推送加载；20 文件精确新审批、下一代租约及实际 Coder 续跑已验证，K1 本身仍在交付 |
| 10-01-console-session-disconnect | console-session-disconnect-20261001 | [completed](10-01-console-session-disconnect/task.json)：后台独立会话及准确断连提示已验证激活；K1新改动的中断恢复另行处理 |
| 10-01-scope-after-coder-timeout | scope-after-coder-timeout-20261001 | [completed](10-01-scope-after-coder-timeout/task.json)：ed12f25已推送加载；真实scope→plan双审批成功，新Coder在新基线执行，K1尚未完成 |
| 10-01-requested-recovery-scope | requested-recovery-scope-20261001 | [completed](10-01-requested-recovery-scope/task.json)：真实测试文件scope已获精确批准并进入新Task，旧Task及历史保留 |
| 10-01-coder-knowledge-wait | coder-knowledge-wait-20261001 | [completed](10-01-coder-knowledge-wait/task.json)：当前 Coder 知识等待已接回、页面等待状态已验证；正式批准知识答复后同 Task 已恢复运行 |
| 09-28-semantic-branch-naming | semantic-branch-naming-20260928 | [completed](09-28-semantic-branch-naming/task.json)：语义分支、审批绑定与恢复归属保护完成；验证报告交付后用户授权提交推送 |
| 09-28-release-delivery-retrospective | release-delivery-retrospective-20260928 | [completed](09-28-release-delivery-retrospective/task.json)：v0.1.2 已发布，业务候选已合并安装，ASE 复盘已落盘 |
| 09-28-project-switch-refresh | project-switch-refresh-20260928 | [completed](09-28-project-switch-refresh/task.json)：4d1e799 / v0.1.2，61 项前端回归及实际 UI 验证 |
| 09-27-delivery-reliability-audit | delivery-reliability-audit | [completed](09-27-delivery-reliability-audit/task.json)：14 阶段审查修复已发布，后续真实交付已 DONE |
| 09-25-joint-approval-delivery | joint-approval-delivery | [completed](09-25-joint-approval-delivery/task.json)：独立 QA/Review、原需求 DONE，Reviewer-only 修复已发布 |
| 09-23-model-routing-ui-followup | model-routing-ui-followup-20260923 | [completed](09-23-model-routing-ui-followup/task.json) |
| 09-23-settings-save-invalid | settings-save-invalid-20260923 | [completed](09-23-settings-save-invalid/task.json) |
| 09-23-agent-model-detail-polish | agent-model-detail-polish-20260923 | [completed](09-23-agent-model-detail-polish/task.json) |
| 09-23-settings-help-popovers | settings-help-popovers-20260923 | [completed](09-23-settings-help-popovers/task.json) |
| 09-23-per-route-cli-connection | per-route-cli-connection-20260923 | [completed](09-23-per-route-cli-connection/task.json) |
| 09-23-model-route-kind-identity | model-route-kind-identity-20260923 | [completed](09-23-model-route-kind-identity/task.json) |
| 08-31-t001-python-cli-bootstrap | task_t001_python_cli | [completed](08-31-t001-python-cli-bootstrap/task.json) |
| 08-31-t002-domain-models | task_t002_domain_models | [completed](08-31-t002-domain-models/task.json) |
| 08-31-t003-sqlite-repository | task_t003_sqlite_repository | [completed](08-31-t003-sqlite-repository/task.json) |
| 08-31-t004-state-machine | task_t004_state_machine | [completed](08-31-t004-state-machine/task.json) |
| 08-31-t005-artifact-store | task_t005_artifact_store | [completed](08-31-t005-artifact-store/task.json) |
| 08-31-t006-git-worktree | task_t006_git_worktree | [completed](08-31-t006-git-worktree/task.json) |
| 08-31-t007-context-builder | task_t007_context_builder | [completed](08-31-t007-context-builder/task.json) |
| 09-01-doc001-readme-stage-archive | DOC001 | [completed](09-01-doc001-readme-stage-archive/task.json) |
| 09-01-t008-fake-agent | task_t008_fake_agent | [completed](09-01-t008-fake-agent/task.json) |
| 09-01-t009-orchestrator | task_t009_orchestrator | [completed](09-01-t009-orchestrator/task.json) |
| 09-01-t010-retry-recovery | task_t010_retry_recovery | [completed](09-01-t010-retry-recovery/task.json) |
| 09-01-t011-real-agent | T011 | [completed](09-01-t011-real-agent/task.json) |
| 09-01-t012-evaluation-handoff | T012 | [completed](09-01-t012-evaluation-handoff/task.json) |
| 09-01-t013-cli-runtime | T013 | [completed](09-01-t013-cli-runtime/task.json) |
| 09-01-t014-runtime-run | T014 | [completed](09-01-t014-runtime-run/task.json) |
| 09-01-t015-command-executor | T015 | [completed](09-01-t015-command-executor/task.json) |
| 09-01-t016-role-worktree-execution | T016 | [completed](09-01-t016-role-worktree-execution/task.json) |
| 09-01-t017-project-workspace | T017 | [completed](09-01-t017-project-workspace/task.json) |
| 09-01-t018-organization-workforce | T018 | [completed](09-01-t018-organization-workforce/task.json) |
| 09-01-t019-portfolio-scheduler | T019 | [completed](09-01-t019-portfolio-scheduler/task.json) |
| 09-01-t020-project-profile | T020 | [completed](09-01-t020-project-profile/task.json) |
| 09-01-t021-spec-compiler | T021 | [completed](09-01-t021-spec-compiler/task.json) |
| 09-01-t022-runtime-workspace-binding | T022 | [completed](09-01-t022-runtime-workspace-binding/task.json) |
| 09-01-t023-evidence-capture | T023 | [completed](09-01-t023-evidence-capture/task.json) |
| 09-01-t024-tool-protocol | T024 | [completed](09-01-t024-tool-protocol/task.json) |
| 09-01-t025-cross-language-e2e | T025 | [completed](09-01-t025-cross-language-e2e/task.json) |
| 09-01-t026-run-projection | T026 | [completed](09-01-t026-run-projection/task.json) |
| 09-01-t027-visualization | T027 | [completed](09-01-t027-visualization/task.json) |
| 09-02-t028-project-manager-entry | T028 | [completed](09-02-t028-project-manager-entry/task.json) |
| 09-02-t029-project-manager-skills | T029 | [completed](09-02-t029-project-manager-skills/task.json) |
| 09-02-t030-product-agent | T030 | [completed](09-02-t030-product-agent/task.json) |
| 09-02-t031-designer-planner-skills | T031 | [completed](09-02-t031-designer-planner-skills/task.json) |
| 09-02-t032-unified-project-entry | T032 | [completed](09-02-t032-unified-project-entry/task.json) |
| 09-04-t034-production-team-host | T034 | [completed](09-04-t034-production-team-host/task.json) |
| 09-05-t035-project-groups | T035 | [completed](09-05-t035-project-groups/task.json) |
| 09-05-t036-live-team | T036 | [completed](09-05-t036-live-team/task.json) |
| 09-06-t037-company-id-bootstrap | T037 | [completed](09-06-t037-company-id-bootstrap/task.json) |
| 09-06-t038-planner-coverage-feedback | T038 | [completed](09-06-t038-planner-coverage-feedback/task.json) |
| 09-06-t039-integration-command-context | T039 | [completed](09-06-t039-integration-command-context/task.json) |
| 09-06-t040-project-baseline-versions | T040 | [completed](09-06-t040-project-baseline-versions/task.json) |
| 09-06-t041-mysql-event-lock-order | T041 | [completed](09-06-t041-mysql-event-lock-order/task.json) |
| 09-06-t042-bounded-delivery-context | T042 | [completed](09-06-t042-bounded-delivery-context/task.json) |
| 09-06-t043-codex-failure-diagnostics | T043 | [completed](09-06-t043-codex-failure-diagnostics/task.json) |
| 09-08-coder-completion-budget | coder-completion-budget | [completed](09-08-coder-completion-budget/task.json) |
| 09-08-coder-platform-finalization | coder-platform-finalization | [completed](09-08-coder-platform-finalization/task.json) |
| 09-08-model-policy-revisions | model-policy-revisions | [completed](09-08-model-policy-revisions/task.json) |
| 09-08-production-role-timeouts | production-role-timeouts | [completed](09-08-production-role-timeouts/task.json) |
| 09-08-t045-coder-continuation-workforce | t045-coder-continuation-workforce | [completed](09-08-t045-coder-continuation-workforce/task.json) |
| 09-08-t046-persistent-work-queue | t046-persistent-work-queue | [completed](09-08-t046-persistent-work-queue/task.json) |
| 09-14-console-layout-hierarchy | console-layout-hierarchy | [completed](09-14-console-layout-hierarchy/task.json) |
| 09-14-knowledge-navigation-hierarchy | knowledge-navigation-hierarchy | [completed](09-14-knowledge-navigation-hierarchy/task.json) |
| 09-14-project-spec-form-ux | project-spec-form-ux | [completed](09-14-project-spec-form-ux/task.json) |
| 09-14-requirement-inputs-agent-models | requirement-inputs-agent-models | [completed](09-14-requirement-inputs-agent-models/task.json) |
| 09-14-spec-center-learning-loop | spec-center-learning-loop | [completed](09-14-spec-center-learning-loop/task.json) |
| 09-15-delivery-queue-blocker-ux | delivery-queue-blocker-ux | [completed](09-15-delivery-queue-blocker-ux/task.json) |
| 09-15-product-dialogue-loop | product-dialogue-loop | [completed](09-15-product-dialogue-loop/task.json) |
| 09-15-requirement-edit-delete | requirement-edit-delete | [completed](09-15-requirement-edit-delete/task.json) |
| 09-17-t047-planner-agent-evolution | T047 | [completed](09-17-t047-planner-agent-evolution/task.json) |
| 09-18-t048-active-knowledge-closure | T048 | [completed](09-18-t048-active-knowledge-closure/task.json) |
| 09-18-t049-incremental-knowledge-indexing | T049 | [completed](09-18-t049-incremental-knowledge-indexing/task.json) |
| 09-18-t050-reviewer-only-verification-recovery | T050 | [completed](09-18-t050-reviewer-only-verification-recovery/task.json) |
| 09-18-t051-joint-recovered-child-convergence | T051 | [completed](09-18-t051-joint-recovered-child-convergence/task.json) |
| 09-18-t052-joint-integration-recovery | T052 | [completed](09-18-t052-joint-integration-recovery/task.json) |
| 09-19-console-readiness | console-readiness | [completed](09-19-console-readiness/task.json) |
| 09-19-documentation-cleanup | documentation-cleanup-20260919 | [completed](09-19-documentation-cleanup/task.json) |
| 09-19-mysql-test-isolation | mysql-test-isolation-20260919 | [completed](09-19-mysql-test-isolation/task.json) |
| 09-21-confirmed-knowledge-display | confirmed-knowledge-display | [completed](09-21-confirmed-knowledge-display/task.json) |
| 09-21-knowledge-resolution-ui | knowledge-resolution-ui | [completed](09-21-knowledge-resolution-ui/task.json) |
| 09-21-trellis-record-normalization | trellis-record-normalization-20260921 | [completed](09-21-trellis-record-normalization/task.json) |

汇总：当前 12；待核实 14；已完成 91。
