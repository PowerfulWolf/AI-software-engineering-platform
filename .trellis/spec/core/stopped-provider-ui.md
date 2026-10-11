# 已停止的提供方前提失败：Console 操作契约

## Scope / Trigger

适用于精确 Coder `FAILED/AUTHENTICATION_ERROR`、非临时故障、无产物的原调用。
调查的 `provider_failure_code` 仅用于选择检查入口；停止、合法草稿、剩余额度与
审批权限仍由应用服务验证。旧失败不能被改写成临时故障，旧调查保留为历史。

## Signatures / Wire

`team_view/app.js` 的 `engineeringStoppedProviderRetryFacts`、
`matchingStoppedProviderRetryPlan`、`submitEngineeringStoppedProviderRetry` 与
`appendEngineeringStoppedProviderRetry` 消费当前 Project/Requirement/Task/WorkItem 的事实。
Console GET manifest 的 `operation_contract_version >= 6` 才允许新入口。

`engineeringCurrentProviderPlan(request, task, step)` 仅组合各目的已通过现有严格 matcher
的计划，选择对应 Operation `updated_at` 最新的当前方案；相同时间以 Operation ID
稳定排序。`source_rebind` 只有携带已核验 `stopped_provider_failure` 时才参与。
`engineeringProviderPlanNextAction(plan)` 让页面与复制报告指向该方案原有的审批入口。
它们不转换 purpose、不重写计划，也不生成新的执行权限。

1. `PROPOSE_EXECUTION_BASELINE`: `purpose=stopped_provider_retry`、
   `input_mode=preserve_draft`，省略 `target_base_ref`；携带当前
   `expected_checkpoint_sha256/task_intent_sha256/task_revision/work_item_id/source_revision`。
2. 当前成功计划包含 `facts.stopped_provider_failure`；其原 outcome/start/capture/stop
   必须绑定同一调用，`process_stop.kind=failed`、非零返回码、`output_present=false`。
   同源目的还必须保持原 source/base、无冲突且没有项目规范变化。
3. `EXECUTE_EXECUTION_BASELINE`: 当前 exact `expected_plan_sha256`、
   `confirm_provider_prerequisites_repaired=true`、`continuation_mode=pause`。
   使用明确新目标的 `source_rebind` 携带该 proof 时也必须确认提供方前提，且保留独立
   native-rule 完整审阅与审批门。
4. 执行后通过既有 latest-bound `RESUME_EXECUTION_BASELINE` 明确继续原需求。

## Contracts

- `DomainModel.to_wire()` 递归省略 None，失败 result 的 `artifact` 缺省与显式 null
  同义。两个已停止执行入口均需接受缺省/null，真实 artifact 则拒绝；浏览器 fixture
  默认使用与公开 wire 一致的缺省字段。
- 尚未准备方案时只说“平台将核验”，不得宣称原执行已停止或草稿已完整封存。
- 当前计划明确说明原认证失败、原记录保留、新执行消耗一次普通开发额度且不退款，
  新执行仍需重新产出及独立 QA/Review。人工 checkbox 是工程决定，不是平台健康探针。
- 页面和复制报告优先当前匹配的恢复方案；旧调查缺项标为历史，不能覆盖当前可用操作。
- 当前方案是带 proof 的 `source_rebind` 时，展示目标版本及原有基线审批，隐藏同源续跑
  的重复准备入口；提供方确认和完整项目规范审阅/确认保持独立。若当前更新方案存在
  冲突，只指向显式 `coder_reapply` 新方案，不承诺旧方案可批准。其他 Project、矛盾
  proof 或不含 provider proof 的普通 source plan 不能取代提供方准备入口。
- 新目的的当前方案使另一目的旧审批控件失效；提交仍使用原精确计划摘要和原目的的
  PAUSE/确认门，不能把 source-rebind 计划交给 stopped-provider 的提交入口。
- 同一个事实/计划的无关轮询保留 checkbox DOM、焦点与阅读内容；计划或作用域变化
  使确认失效。旧 detached callback、未勾选、旧能力版本、读取不可用和其他 Project
  都在提交前重新拒绝，不能只依赖按钮 disabled。
- 当前提供方失败不同时展示必然失败的 completed-output 入口。

## Validation Matrix / Good / Base / Bad

| 情况 | 必须表现 |
| --- | --- |
| 当前 AUTH hint、无方案 | 单个“准备保留进度的续跑方案”，不声称已修复 |
| 精确成功方案且未确认 | 原因、保存内容、额度与下一步可见，审批不可提交 |
| 精确方案且明确确认 | 仅 PAUSE；之后单独继续，不启动重复原调用 |
| source_rebind 携带 proof | 提供方确认与完整 native-rule 审阅都满足才能 PAUSE |
| 当前 source_rebind，历史同源方案/收集失败 | 单个当前审批；下一步与目标版本一致，旧调查只作历史 |
| completed/zero/output-present 的矛盾 stop | 不接受为当前提供方失败方案 |
| Project/checkpoint/source/plan/capability 已变化 | 旧 callback 零 POST；确认重置 |
| 无关轮询 | 已勾选和焦点保留，390px/1440px 关键内容可见 |

Good：修复认证配置，查看精确核验方案，确认并保留进度，随后明确继续同一需求。
Base：旧服务版本和旧失败仍可只读，显示能力限制；不改历史。
Bad：后台 MCP 认证日志决定主调用结果、checkbox 冒充健康核验、重复调查补造缺失事实，
或者为了继续而退款或重建需求。

## Tests / Stored Data / Rollback

`tests/team_view/stopped-provider-retry.test.cjs` 校验完整入口、精确 callback、PAUSE、
普通额度、source-rebind 联合确认及复制报告；
`tests/team_view/browser/stopped-provider-retry.test.cjs` 用真实 Chrome 检查轮询、焦点、
宽窄布局、两种目的的计划变化重置与 detached callback 零 POST；source-rebind
另核验完整规范读取前不能确认、两项同事实 consent DOM 保留且各自独立。
`tests/web_console/test_transport.py::test_console_operation_manifest_reports_the_running_action_contract`
校验运行能力版本。公开 Host/MySQL fixture 必须通过真实停止、PAUSE/RESUME、新 claim、
同一候选的独立 QA PASS/Review APPROVE；fixture 成功不是生产 K1 已完成。

无需改库或重写历史。空闲边界受控加载后，刷新原需求并重新调查，准备精确方案；
已有精确 source-rebind 方案时刷新后直接核对其目标版本、原认证前提及项目规范，
按原基线审批保持暂停，无需另准备同源方案。
工程授权者修复或核验原认证/执行配置、明确确认后 PAUSE，再单独 RESUME。
旧拒绝结果、原 Task/分支和完整现场保持。已有新恢复记录时保留兼容读取代码；
回滚不得清空现场、复活旧 WorkItem 或把旧授权解释为新的继续权限。
