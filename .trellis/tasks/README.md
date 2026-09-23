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

原报告及历史路径保留。T047 曾重号，使用唯一目录名区分，详见 [当前路线](../../docs/milestones.md)。

| 目录 | 任务 ID | 状态记录 |
|---|---|---|
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

汇总：当前 5；待核实 14；已完成 69。
