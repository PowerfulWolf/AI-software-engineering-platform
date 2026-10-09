const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");
const { supportedActions } = require("../console-capabilities-fixture.cjs");

async function rescueUi(t, version = 4) {
  const h = await ui(t, {operationManifest: {operation_contract_version: version, supported_actions: supportedActions}});
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_rescue"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "原执行结果待核验，旧进度保留。", next_action: "平台检查原执行。"};
  const facts = {task_id: "task_rescue", work_item_id: "work_rescue", role: "coder",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  const task = {id: "delivery_rescue", task_id: facts.task_id, task_revision: 4,
    task_intent_sha256: facts.task_intent_sha256, request_id: request.id, project_id: request.project_id,
    title: request.title, status: "IMPLEMENTING", terminal: false, scope: request.scopes[0],
    last_activity: "2026-10-05T00:00:00Z", execution: request.execution,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: [step]};
  h.team.tasks.push(task);
  const waitIntent = {action: "HANDLE_DELIVERY_WAIT", project_id: request.project_id, delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256, work_item_id: facts.work_item_id,
    expected_disposition_sha256: step.wait_disposition_sha256, expected_task_intent_sha256: facts.task_intent_sha256,
    expected_source_revision: facts.source_revision, expected_checkpoint_sequence: 4};
  const proof = {kind: "delivery_wait_investigation", ...facts, disposition_sha256: step.wait_disposition_sha256,
    proof_sha256: "e".repeat(64), original_run_id: "run_original", inspected_at: "2026-10-05T01:00:00Z",
    missing: ["OUTCOME_UNKNOWN", "STOP_UNRECORDED", "CHECKPOINT_UNAVAILABLE"], permitted_resolutions: [],
    next_action: "平台未找到原执行的完整记录。"};
  const handling = {kind: "delivery_wait_handling", schema_version: "v1", ...facts,
    disposition_sha256: step.wait_disposition_sha256, investigation: proof, status: "PLATFORM_ATTENTION",
    manual_resolution_allowed: false, handling_sha256: "f".repeat(64), handled_at: "2026-10-05T01:00:00Z",
    summary: "原执行记录不完整，不能安全继续。", user_action: "将处理报告交给平台维护者。",
    recheck_when: "平台补齐原记录后再检查。"};
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_old_handling", intent: waitIntent,
    updated_at: "2026-10-05T01:00:00Z", result: {checkpoint_sha256: request.checkpoint_sha256, engineering_wait_handling: handling}}));
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_rescue_" + submitted.length,
      intent, updated_at: `2026-10-06T0${submitted.length}:00:00Z`});
    h.state.operations.push(record);
    return route.fulfill({status: 202, json: record});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  if (await h.page.locator("#notification").isVisible()) await h.close();
  return {h, request, task, step, facts, proof, handling, submitted,
    card: h.page.locator('#detail .engineering-rescue-panel[data-key="engineering:work_rescue:rescue"]')};
}

function planFor(fixture) {
  return {purpose: "legacy_workspace_rescue", plan_sha256: "1".repeat(64), target_base_ref: fixture.facts.source_revision,
    input_mode: "preserve_draft", conflicted: false, dirty_capture: {source_revision: fixture.facts.source_revision},
    facts: {task: {id: fixture.task.task_id, branch_name: "ai/feature/original"}, task_revision: 4,
      work_item_id: fixture.step.work_item_id, legacy_containment: {
        original_start: {work_item_id: fixture.step.work_item_id, request: {run_id: fixture.proof.original_run_id},
          started_at: "2026-10-05T02:00:00Z", start_sha256: "2".repeat(64)},
        boot: {booted_at: "2026-10-06T00:00:00Z", machine_sha256: "3".repeat(64), boot_session_sha256: "4".repeat(64)},
        containment_sha256: "5".repeat(64)}}};
}

test("legacy rescue is visible, preserves same demand and only proceeds after explicit engineering confirmation", async t => {
  const fixture = await rescueUi(t);
  const {h, request, task, submitted, card} = fixture;
  assert.equal(await card.isVisible(), true);
  assert.equal(await card.evaluate(node => node.tagName), "SECTION");
  assert.match(await card.innerText(), /旧执行结果仍未知/);
  assert.match(await card.innerText(), /下一轮使用剩余工作额度/);
  assert.match(await card.innerText(), /先由平台检查当前本机执行和保留进度/);
  assert.doesNotMatch(await card.innerText(), /需重启原执行所在的整台电脑/);
  assert.equal(await card.getByRole("textbox").count(), 0, "a product user does not enter commit hashes");
  assert.doesNotMatch(await h.page.locator("#detail .engineering-wait-facts").innerText(), /将处理报告交给平台维护者/);
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  assert.equal(submitted[0].purpose, "legacy_workspace_rescue");
  assert.equal(submitted[0].input_mode, "preserve_draft");
  assert.equal(submitted[0].target_base_ref, fixture.facts.source_revision);
  const plan = planFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  h.state.operationManifest.operation_contract_version = 4;
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await card.innerText(), /原执行开始/);
  assert.match(await card.innerText(), /方案核验的整机启动/);
  const checkbox = card.getByRole("checkbox", {name: "确认原执行在同一电脑且已整机重启"});
  const approve = card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  assert.equal(await approve.isDisabled(), true);
  assert.equal(await checkbox.isChecked(), false);
  assert.match(await card.innerText(), /工程授权者身份/);
  assert.match(await card.innerText(), /未迁移或远程执行/);
  const binding = card.locator("details.engineering-details");
  assert.equal(await binding.evaluate(node => node.open), false);
  await checkbox.check();
  await checkbox.evaluate(node => {window.rescueCheckbox = node; window.rescueControls = node.closest(".engineering-baseline-form");});
  request.title += " · 仅标题变化";
  task.last_activity = "2026-10-06T03:00:00Z";
  await h.tick();
  assert.equal(await checkbox.evaluate(node => node === window.rescueCheckbox &&
    node.closest(".engineering-baseline-form") === window.rescueControls), true);
  assert.equal(await checkbox.isChecked(), true, "polling unrelated facts keeps the explicit decision draft");
  assert.equal(await approve.isEnabled(), true);
  for (const width of [1440, 1024, 390]) {
    await h.page.setViewportSize({width, height: 1000});
    assert.equal(await card.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.locator("#detail").evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await h.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  }
  assert.equal(submitted.length, 1, "polling and confirmation do not submit an approval");
  await approve.click();
  await h.close();
  assert.equal(submitted[1].action, "EXECUTE_EXECUTION_BASELINE");
  assert.equal(submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.equal(submitted[1].confirm_legacy_containment, true);
  assert.equal(Object.hasOwn(submitted[1], "booted_at"), false);
  assert.equal(Object.hasOwn(submitted[1], "operator_id"), false);
  assert.match(await h.page.locator("#detail .product-execution-summary").innerText(), /等待工程处理/);
  await h.page.locator('#detail .request-history-fold[data-key^="operation-history:"] > summary').click();
  assert.match(await h.page.locator("#detail").innerText(), /当次用户操作 · 将处理报告交给平台维护者/);
  assert.match(await h.page.locator("#detail").innerText(), /当次恢复方案 · 保留原需求分支/);
});

test("old service and withdrawn capability cannot submit the new rescue purpose or stale engineering approval", async t => {
  const fixture = await rescueUi(t, 1);
  const {h, request, submitted, card} = fixture;
  assert.match(await card.innerText(), /当前服务尚不支持此恢复路径/);
  assert.equal(await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).count(), 0);
  h.state.operationManifest.operation_contract_version = 2;
  await h.tick();
  const prepare = card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true});
  await prepare.evaluate(node => {window.oldRescuePrepare = node;});
  h.state.operationManifest.operation_contract_version = 1;
  await h.tick();
  assert.equal(await prepare.count(), 0);
  await h.page.evaluate(() => window.oldRescuePrepare.click());
  assert.equal(submitted.length, 0);
  await h.close();
  h.state.operationManifest.operation_contract_version = 2;
  await h.tick();
  await prepare.click();
  await h.close();
  const plan = planFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  h.state.operationManifest.operation_contract_version = 4;
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await card.getByRole("checkbox").check();
  const approve = card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  await approve.evaluate(node => {window.oldRescueApprove = node;});
  request.checkpoint_sha256 = "6".repeat(64);
  await h.tick();
  assert.equal(await approve.count(), 0, "a changed checkpoint invalidates old plan and explicit confirmation");
  await h.page.evaluate(() => window.oldRescueApprove.click());
  assert.equal(submitted.length, 1, "a retained approval closure cannot start a successor with stale facts");
});

test("a prepared rescue can be prepared again after execution rejects changed facts", async t => {
  const fixture = await rescueUi(t);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = planFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await card.getByRole("checkbox").check();
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).evaluate(node => {
    window.rejectedRescueApproval = node;
  });
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).click();
  await h.close();
  Object.assign(h.state.operations[2], {status: "FAILED", error_code: "COMMAND_REJECTED",
    error_summary: "现场变化，请重新准备方案。"});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await card.getByRole("button", {name: "重新准备恢复方案", exact: true}).click();
  await h.close();
  assert.equal(submitted[2].purpose, "legacy_workspace_rescue");
  const fresh = planFor(fixture);
  fresh.plan_sha256 = "6".repeat(64);
  fresh.facts.legacy_containment.boot.boot_session_sha256 = "7".repeat(64);
  fresh.facts.legacy_containment.containment_sha256 = "8".repeat(64);
  Object.assign(h.state.operations[3], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: fresh}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await card.getByRole("checkbox").isChecked(), false);
  await h.page.evaluate(() => window.rejectedRescueApproval.click());
  assert.equal(submitted.length, 3, "the superseded plan closure is refused");
  await h.close();
  await card.getByRole("checkbox").check();
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).click();
  await h.close();
  assert.equal(submitted[3].expected_plan_sha256, fresh.plan_sha256);
});

function localPlanFor(fixture) {
  const plan = planFor(fixture);
  plan.dirty_capture.worktree_path = "/fixture/coder";
  const containment = plan.facts.legacy_containment;
  containment.method = "operator_confirmed_local_stop";
  containment.boot.booted_at = "2026-10-01T00:00:00Z";
  containment.local_execution_survey = {worktree_path: "/fixture/coder",
    machine_sha256: containment.boot.machine_sha256, boot_session_sha256: containment.boot.boot_session_sha256,
    account_sha256: "6".repeat(64), observed_at: "2026-10-06T00:00:00Z", scanner_version: "local-v1",
    blockers: [], survey_sha256: "7".repeat(64)};
  return plan;
}

test("operations read failure explains missing recovery controls after the toast closes and requires fresh approval on recovery", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = localPlanFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true})
    .evaluate(node => {window.beforeReadFailureApproval = node;});
  const failRead = route => route.request().method() === "GET"
    ? route.fulfill({status: 500, json: {error: {message: "operation read unavailable"}}}) : route.fallback();
  await h.page.route("http://ui.test/api/v1/operations", failRead);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  const wait = h.page.locator("#detail .engineering-wait-panel");
  const unavailable = wait.locator(".engineering-controls-unavailable").first();
  assert.equal(await wait.locator(".engineering-controls-unavailable").count(), 2,
    "retained wait and rescue history each explain their unavailable current controls");
  assert.equal(await unavailable.isVisible(), true);
  assert.match(await unavailable.innerText(), /交付操作记录读取失败/);
  assert.match(await unavailable.innerText(), /不能确认当前恢复方案与审批状态/);
  assert.match(await unavailable.innerText(), /修复操作记录读取/);
  assert.match(await unavailable.innerText(), /不要重复准备方案或重建需求/);
  assert.doesNotMatch(await wait.locator(".engineering-wait-facts").innerText(), /你可以点击|点击“准备保留进度的恢复方案”/);
  assert.equal(await wait.getByRole("button", {name: "调查工程等待", exact: true}).count(), 0);
  assert.equal(await wait.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).count(), 0);
  assert.equal(await card.count(), 1, "the read-only rescue explanation remains available");
  assert.equal(await card.getByText(/计划摘要 ·/).count(), 0,
    "the retained history cannot become a current recovery plan");
  await h.page.evaluate(() => window.beforeReadFailureApproval.click());
  assert.equal(submitted.length, 1, "the retained control cannot submit while operation facts are unavailable");
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.tick();
  assert.equal(await h.page.locator("#notification").isVisible(), false);
  assert.equal(await unavailable.isVisible(), true, "the next step persists after notification acknowledgment and polling");
  await h.page.unroute("http://ui.test/api/v1/operations", failRead);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await unavailable.count(), 0);
  assert.equal(await card.isVisible(), true);
  const approve = card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.equal(await approve.isEnabled(), true, "the current button submits confirmation only when clicked");
  assert.equal(submitted.length, 1, "successful reads do not approve or execute recovery");
  await approve.click();
  await h.close();
  assert.equal(submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.equal(submitted[1].confirm_local_execution_stopped, true);
  assert.equal(submitted[1].expected_checkpoint_sha256, request.checkpoint_sha256);
});

test("simultaneous team and operation read failure revokes recovery controls while preserving detail reading state", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = localPlanFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  const binding = h.page.locator("#detail .engineering-wait-binding");
  await binding.locator("summary").first().click();
  await binding.evaluate(node => {window.beforeFailedRefreshBinding = node;});
  assert.equal(await card.getByRole("checkbox").count(), 0);
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true})
    .evaluate(node => {window.beforeFailedRefreshApproval = node;});
  const failRead = route => route.fulfill({status: 500, json: {error: {message: "read unavailable"}}});
  await h.page.route("http://ui.test/api/v1/team?*", failRead);
  await h.page.route("http://ui.test/api/v1/operations", failRead);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  const wait = h.page.locator("#detail .engineering-wait-panel");
  const unavailable = wait.locator(".engineering-controls-unavailable").first();
  assert.equal(await wait.locator(".engineering-controls-unavailable").count(), 2);
  assert.equal(await unavailable.isVisible(), true);
  assert.match(await unavailable.innerText(), /交付操作记录读取失败/);
  assert.match(await unavailable.innerText(), /修复操作记录读取/);
  assert.equal(await wait.getByRole("checkbox").count(), 0);
  assert.equal(await wait.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).count(), 0);
  assert.equal(await binding.evaluate(node => node === window.beforeFailedRefreshBinding && node.open), true,
    "the unrelated investigation disclosure remains open and is not rebuilt");
  await h.page.evaluate(() => window.beforeFailedRefreshApproval.click());
  assert.equal(submitted.length, 1);
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await h.tick();
  assert.equal(await h.page.locator("#notification").isVisible(), false);
  assert.equal(await unavailable.isVisible(), true, "a failed Team snapshot does not hide the persistent control explanation");
  await h.page.unroute("http://ui.test/api/v1/team?*", failRead);
  await h.page.unroute("http://ui.test/api/v1/operations", failRead);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await unavailable.count(), 0);
  assert.equal(await binding.evaluate(node => node === window.beforeFailedRefreshBinding && node.open), true);
  const approve = card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.equal(await approve.isEnabled(), true);
  await h.page.evaluate(() => window.beforeFailedRefreshApproval.click());
  assert.equal(submitted.length, 1, "a disconnected approval cannot revive after connectivity returns");
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await approve.click();
  await h.close();
  assert.equal(submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.equal(submitted[1].confirm_local_execution_stopped, true);
});

test("failed Team refresh renders control guidance without replacing a business draft", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, submitted} = fixture;
  await h.draft();
  const draft = h.page.locator('#composer input[name="name"]');
  const failRead = route => route.fulfill({status: 500, json: {error: {message: "read unavailable"}}});
  await h.page.route("http://ui.test/api/v1/team?*", failRead);
  await h.page.route("http://ui.test/api/v1/operations", failRead);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await draft.evaluate(node => node === window.draftInput), true);
  assert.equal(await draft.inputValue(), "保留正在编辑的需求");
  assert.equal(await h.page.locator("#composer").isVisible(), true);
  assert.match(await h.page.locator("#detail .engineering-controls-unavailable").first().innerText(), /交付操作记录读取失败/);
  await h.page.unroute("http://ui.test/api/v1/team?*", failRead);
  await h.page.unroute("http://ui.test/api/v1/operations", failRead);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await draft.evaluate(node => node === window.draftInput), true);
  assert.equal(await draft.inputValue(), "保留正在编辑的需求");
  assert.equal(submitted.length, 0, "read failures and draft preservation do not create requirements or recovery actions");
});

test("local rescue confirms the visible declaration on explicit approval without a separate checkbox", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = localPlanFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await card.innerText(), /该检查不能证明旧调用已经停止/);
  assert.match(await card.innerText(), /本机检查时间/);
  assert.match(await card.innerText(), /同一账户本地执行/);
  assert.match(await card.innerText(), /原调用及全部派生工具已结束/);
  assert.match(await card.innerText(), /此确认是独立人工工程授权/);
  assert.doesNotMatch(await card.innerText(), /方案核验的整机启动|原执行之后已重启整台电脑/);
  const approve = card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true});
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.match(await card.locator(".engineering-rescue-confirmation").innerText(), /点击“批准保留进度，保持暂停”即表示你以工程授权者身份确认/);
  assert.equal(await approve.isEnabled(), true);
  await approve.evaluate(node => {window.localRescueApproval = node;});
  request.title += " · harmless polling";
  await h.tick();
  assert.equal(await approve.evaluate(node => node === window.localRescueApproval), true);
  assert.equal(submitted.length, 1, "loading and polling a prepared plan cannot submit confirmation or execute recovery");
  await approve.click();
  await h.close();
  assert.equal(submitted[1].confirm_local_execution_stopped, true);
  assert.equal(Object.hasOwn(submitted[1], "confirm_legacy_containment"), false);
  assert.equal(Object.hasOwn(submitted[1], "local_execution_survey"), false);
  assert.equal(submitted[1].expected_plan_sha256, plan.plan_sha256);
  assert.match(submitted[1].reference, /全部派生工具已结束/);
  await h.page.locator('#detail .request-history-fold[data-key^="operation-history:"] > summary').click();
  await h.page.locator('#detail .request-history-fold .execution-history-entry').filter({hasText: "当次恢复方案"})
    .locator("details > summary").click();
  assert.match(await h.page.locator("#detail").innerText(), /当次本机检查/);
  assert.doesNotMatch(await h.page.locator("#detail").innerText(), /当次整机启动/);
});

test("an unmet rescue prerequisite is a clear checked wait without approval and can be checked again", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, task, step, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const preparation = {status: "WAITING", task_id: task.task_id, work_item_id: step.work_item_id,
    source_revision: fixture.facts.source_revision, code: "LOCAL_EXECUTION_ACTIVE",
    summary: "当前仍有本机执行占用保留的工作现场。", next_action: "等待原调用及派生工具结束后重新检查恢复前提。",
    responsible_party: "平台执行服务"};
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, legacy_rescue_preparation: preparation}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await card.innerText(), /恢复前提尚未满足/);
  assert.match(await card.innerText(), /当前仍有本机执行占用/);
  assert.match(await card.innerText(), /处理方 · 平台执行服务/);
  assert.match(await card.innerText(), /本次检查没有生成恢复方案、保存审批或启动 Coder/);
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.equal(await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).count(), 0);
  assert.equal(submitted.length, 1);
  await card.getByRole("button", {name: "重新检查恢复前提", exact: true}).click();
  await h.close();
  assert.equal(submitted.length, 2);
  assert.equal(submitted[1].action, "PROPOSE_EXECUTION_BASELINE");
  assert.equal(Object.hasOwn(submitted[1], "confirm_local_execution_stopped"), false);
});

test("a local stop approval is withdrawn on version downgrade or changed survey", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = localPlanFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).evaluate(node => {window.localStaleApproval = node;});
  h.state.operationManifest.operation_contract_version = 2;
  await h.tick();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.match(await card.innerText(), /当前服务尚不支持此恢复路径/);
  await h.page.evaluate(() => window.localStaleApproval.click());
  assert.equal(submitted.length, 1);
  await h.close();
  h.state.operationManifest.operation_contract_version = 4;
  await h.tick();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.equal(await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).isEnabled(), true);
  plan.plan_sha256 = "8".repeat(64);
  plan.facts.legacy_containment.local_execution_survey.survey_sha256 = "9".repeat(64);
  await h.tick();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  await h.page.evaluate(() => window.localStaleApproval.click());
  assert.equal(submitted.length, 1);
});

test("failed rescue preparation is the visible current result and copied report after later handling", async t => {
  for (const status of ["FAILED", "INTERRUPTED"]) {
    await t.test(status, async current => {
      const fixture = await rescueUi(current, 3);
      const {h, request, card, submitted} = fixture;
      await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
      await h.close();
      const summary = "Manager 执行异常(WorktreeCaptureRejected); 尚未获得具体原因。请提供此操作编号排查, 不要反复重试。";
      Object.assign(h.state.operations[1], {status, error_code: "MANAGER_FAILURE", error_summary: summary});
      h.state.operations.push(operation("SUCCEEDED", {operation_id: "later_handling",
        intent: {...h.state.operations[0].intent}, updated_at: "2026-10-08T02:00:00Z",
        result: structuredClone(h.state.operations[0].result)}));
      await h.tick();
      if (await h.page.locator("#notification").isVisible()) await h.close();
      assert.match(await card.innerText(), /恢复方案准备(?:失败|被中断)/);
      assert.match(await card.innerText(), /平台维护者/);
      assert.match(await h.page.locator("#detail .engineering-wait-facts").innerText(), /平台在准备恢复方案时发生内部异常/);
      assert.equal(await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).count(), 0);
      assert.equal(await card.getByRole("checkbox").count(), 0);
      await h.page.evaluate(() => Object.defineProperty(navigator, "clipboard", {configurable: true,
        value: {writeText: async value => {window.copiedRecoveryFailure = value;}}}));
      await h.page.locator("#detail").getByRole("button", {name: "复制处理报告", exact: true}).click();
      const report = await h.page.evaluate(() => window.copiedRecoveryFailure);
      assert.match(report, /恢复方案准备(?:失败|被中断)/);
      assert.match(report, /恢复准备操作 · operation_rescue_1/);
      assert.match(report, /错误编号 · MANAGER_FAILURE/);
      assert.ok(report.includes(summary), "preserve the platform's safe original diagnostic");
      assert.doesNotMatch(report, /在当前需求详情点击“准备保留进度的恢复方案”/);
      assert.equal(submitted.length, 1, "rendering and copying do not approve or run recovery");
    });
  }
});

test("foreign failures do not replace a ready rescue and a current failure revokes stale approval", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = localPlanFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).evaluate(node => {window.failureStaleApproval = node;});
  for (const [key, value] of Object.entries({project_id: "project_other", delivery_id: "request_other",
    task_id: "task_other", expected_checkpoint_sha256: "9".repeat(64), expected_task_revision: 5,
    expected_task_intent_sha256: "9".repeat(64), expected_work_item_id: "work_other",
    expected_source_revision: "9".repeat(40), purpose: "source_rebind", input_mode: "coder_reapply",
    target_base_ref: "9".repeat(40)})) {
    h.state.operations.push(operation("FAILED", {operation_id: "foreign_rescue_" + key,
      updated_at: "2026-10-08T02:00:00Z", error_code: "MANAGER_FAILURE", error_summary: "foreign failure",
      intent: {...h.state.operations[1].intent, [key]: value}, result: null}));
  }
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.equal(await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).isEnabled(), true);
  assert.doesNotMatch(await card.innerText(), /foreign failure|MANAGER_FAILURE/);
  h.state.operations.push(operation("FAILED", {operation_id: "current_rescue_failure",
    updated_at: "2026-10-09T02:00:00Z", error_code: "MANAGER_FAILURE", error_summary: "internal failure",
    intent: {...h.state.operations[1].intent}, result: null}));
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.equal(await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).count(), 0);
  assert.match(await card.innerText(), /恢复方案准备失败/);
  await h.page.evaluate(() => window.failureStaleApproval.click());
  assert.equal(submitted.length, 1, "the superseded approval cannot submit");
});

test("a checked capture refusal keeps the saved draft and uses its maintenance step in the report", async t => {
  const fixture = await rescueUi(t, 4);
  const {h, request, task, step, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const preparation = {status: "WAITING", task_id: task.task_id, work_item_id: step.work_item_id,
    source_revision: fixture.facts.source_revision, code: "LEGACY_WORKSPACE_CAPTURE_REJECTED",
    summary: "保留进度的完整草稿暂时无法封存, 原文件与开发进度已保留。",
    next_action: "请由平台维护者检查草稿捕获的文件格式、权限和敏感信息校验；处理后重新准备恢复方案，不要清空工作区或重建需求。",
    responsible_party: "平台执行服务"};
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, legacy_rescue_preparation: preparation}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await card.innerText(), /恢复前提尚未满足/);
  assert.match(await card.innerText(), /原文件与开发进度已保留/);
  assert.doesNotMatch(await card.innerText(), /恢复方案准备失败|内部异常/);
  assert.equal(await card.getByRole("checkbox").count(), 0);
  await h.page.evaluate(() => Object.defineProperty(navigator, "clipboard", {configurable: true,
    value: {writeText: async value => {window.copiedCaptureWait = value;}}}));
  await h.page.locator("#detail").getByRole("button", {name: "复制处理报告", exact: true}).click();
  const report = await h.page.evaluate(() => window.copiedCaptureWait);
  assert.ok(report.includes("用户操作 · " + preparation.next_action));
  assert.doesNotMatch(report, /在当前需求详情点击“准备保留进度的恢复方案”/);
  assert.equal(submitted.length, 1);
});

test("approved preservation stays paused, complete native rule review precedes source approval and continuation", async t => {
  const fixture = await rescueUi(t);
  const {h, request, task, step, facts, submitted, card} = fixture;
  const plan = planFor(fixture);
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_ready_original", updated_at: "2026-10-06T02:00:00Z",
    intent: {action: "PROPOSE_EXECUTION_BASELINE", purpose: "legacy_workspace_rescue", project_id: request.project_id,
      delivery_id: request.id, expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
      expected_task_intent_sha256: task.task_intent_sha256, expected_task_revision: 4, expected_work_item_id: step.work_item_id,
      expected_source_revision: facts.source_revision, target_base_ref: facts.source_revision, input_mode: "preserve_draft"},
    result: {checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}}));
  await h.tick();
  await card.getByRole("checkbox").check();
  await card.getByRole("button", {name: "批准保留进度，保持暂停", exact: true}).click();
  await h.close();
  assert.equal(submitted[0].continuation_mode, "pause");
  Object.assign(h.state.operations.at(-1), {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, stage: "ENGINEERING_BASELINE_UPDATED",
    next_action: "完整进度已保存，交付保持暂停。"}});
  Object.assign(facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: "8".repeat(64), work_item_id: "work_preserved"});
  step.work_item_id = facts.work_item_id;
  step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  request.execution.reason_code = "EXECUTION_BASELINE_PAUSED";
  await h.tick();
  const pause = h.page.locator("#detail .engineering-baseline-pause");
  assert.equal(await pause.isVisible(), true);
  assert.match(await pause.innerText(), /进度已保留 · 交付暂停/);
  assert.equal(await pause.getByRole("button", {name: "调查工程等待", exact: true}).count(), 0);
  assert.equal(submitted.length, 1, "preservation and polling do not invoke continuation");
  await pause.getByRole("textbox", {name: "目标代码完整版本"}).fill("f".repeat(40));
  await pause.getByRole("button", {name: "调查并保留原草稿", exact: true}).click();
  await h.close();
  const delta = {path: "AGENTS.md", change: "modified", before: {sha256: "2".repeat(64)}, after: {sha256: "3".repeat(64)}};
  const epoch = {epoch_sha256: "4".repeat(64), target_base_ref: "f".repeat(40)};
  const newPlan = {plan_sha256: "9".repeat(64), target_base_ref: "f".repeat(40), input_mode: "preserve_draft", conflicted: false,
    dirty_capture: {source_revision: facts.source_revision}, facts: {task: {id: task.task_id, branch_name: "ai/feature/original"},
      task_revision: 4, work_item_id: step.work_item_id, native_rule_change: {change_sha256: "7".repeat(64), target: epoch, changes: [delta]}}};
  Object.assign(h.state.operations.at(-1), {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: newPlan}});
  await h.page.route("http://ui.test/api/v1/operations/*/native-rules?*", route => route.fulfill({json: {
    delta, epoch, unified_diff: "--- AGENTS.md\n+++ AGENTS.md\n+<script>window.ruleAttack=true</script>\n+run incremental tests"}}));
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  const approve = pause.getByRole("button", {name: "批准更新基线，保持暂停", exact: true});
  const confirmation = pause.getByRole("checkbox", {name: "确认目标版本的项目规范变更"});
  assert.equal(await confirmation.isDisabled(), true);
  assert.equal(await approve.isDisabled(), true);
  await pause.getByRole("button", {name: "查看规范变更 · AGENTS.md", exact: true}).click();
  await confirmation.waitFor();
  await h.page.waitForFunction(() => document.querySelector('[aria-label="确认目标版本的项目规范变更"]')?.disabled === false);
  const review = pause.locator(".engineering-native-rule-changes details");
  await review.locator("summary").click();
  assert.match(await review.innerText(), /run incremental tests/);
  assert.equal(await h.page.evaluate(() => window.ruleAttack), undefined);
  await confirmation.check();
  await review.evaluate(node => {window.retainedNativeReview = node;});
  task.last_activity = "2026-10-07T02:00:00Z";
  await h.tick();
  assert.equal(await review.evaluate(node => node === window.retainedNativeReview && node.open), true);
  assert.equal(await confirmation.isChecked(), true);
  await approve.click();
  await h.close();
  assert.equal(submitted[2].continuation_mode, "pause");
  assert.equal(submitted[2].approved_native_rule_change_sha256, "7".repeat(64));
  Object.assign(h.state.operations.at(-1), {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, stage: "ENGINEERING_BASELINE_UPDATED", next_action: "基线已更新，保持暂停。"}});
  facts.source_revision = "f".repeat(40);
  facts.execution_baseline_sha256 = "6".repeat(64);
  step.wait_disposition_sha256 = "5".repeat(64);
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.equal(submitted.length, 3);
  await pause.getByRole("button", {name: "继续原需求", exact: true}).click();
  await h.close();
  assert.equal(submitted[3].action, "RESUME_EXECUTION_BASELINE");
  assert.equal(submitted[3].expected_execution_baseline_sha256, "6".repeat(64));
  assert.equal(submitted[3].expected_source_revision, "f".repeat(40));
});

test("two repository rule reviews and explicit consent survive each other and polling", async t => {
  const {h, request, task, step, facts, submitted} = await rescueUi(t);
  Object.assign(facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: "8".repeat(64)});
  step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  request.execution.reason_code = "EXECUTION_BASELINE_PAUSED";
  const otherTask = structuredClone(task);
  otherTask.id = "delivery_other";
  otherTask.task_id = "task_other";
  otherTask.scope.delivery_id = otherTask.id;
  const otherStep = otherTask.role_queue[0];
  otherStep.work_item_id = "work_other";
  Object.assign(otherStep.wait_disposition.facts, {task_id: otherTask.task_id, work_item_id: otherStep.work_item_id});
  h.team.tasks.push(otherTask);
  request.scopes.push(otherTask.scope);
  const plans = [task, otherTask].map((currentTask, index) => {
    const currentStep = currentTask.role_queue[0];
    const delta = {path: "AGENTS.md", change: "modified", before: {sha256: "2".repeat(64)}, after: {sha256: "3".repeat(64)}};
    const epoch = {epoch_sha256: String(index + 4).repeat(64), target_base_ref: "f".repeat(40)};
    const plan = {plan_sha256: String(index + 6).repeat(64), target_base_ref: "f".repeat(40), input_mode: "preserve_draft", conflicted: false,
      dirty_capture: {source_revision: facts.source_revision}, facts: {task: {id: currentTask.task_id, branch_name: "ai/feature/original"},
        task_revision: 4, work_item_id: currentStep.work_item_id,
        native_rule_change: {change_sha256: String(index + 8).repeat(64), target: epoch, changes: [delta]}}};
    const record = operation("SUCCEEDED", {operation_id: "operation_native_" + index, updated_at: "2026-10-06T02:00:00Z",
      intent: {action: "PROPOSE_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
        expected_checkpoint_sha256: request.checkpoint_sha256, task_id: currentTask.task_id,
        expected_task_intent_sha256: currentTask.task_intent_sha256, expected_task_revision: 4,
        expected_work_item_id: currentStep.work_item_id, expected_source_revision: facts.source_revision,
        target_base_ref: plan.target_base_ref, input_mode: plan.input_mode},
      result: {checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
    h.state.operations.push(record);
    return {plan, record, inspection: {delta, epoch, unified_diff: "--- AGENTS.md\n+++ AGENTS.md\n+repository " + index + " complete rules"}};
  });
  await h.page.route("http://ui.test/api/v1/operations/*/native-rules?*", route => {
    const record = plans.find(item => route.request().url().includes(item.record.operation_id));
    return route.fulfill({json: record.inspection});
  });
  await h.tick();
  const cards = [step, otherStep].map(currentStep => h.page.locator(
    '#detail .engineering-baseline-pause[data-key="engineering:' + currentStep.work_item_id + ':pause"]'));
  for (const [index, card] of cards.entries()) {
    const confirmation = card.getByRole("checkbox", {name: "确认目标版本的项目规范变更"});
    assert.equal(await confirmation.isDisabled(), true);
    await card.getByRole("button", {name: "查看规范变更 · AGENTS.md", exact: true}).click();
    await h.page.waitForFunction(work => document.querySelector(
      '[data-key="engineering:' + work + ':pause"] [aria-label="确认目标版本的项目规范变更"]')?.disabled === false, [step, otherStep][index].work_item_id);
    const review = card.locator(".engineering-native-rule-changes details");
    await review.locator("summary").click();
    await confirmation.check();
    await review.evaluate((node, index) => {
      window.retainedRepositoryReviews ||= [];
      window.retainedRepositoryReviews[index] = node;
    }, index);
  }
  task.last_activity = "2026-10-07T02:00:00Z";
  otherTask.last_activity = "2026-10-07T03:00:00Z";
  await h.tick();
  for (const [index, card] of cards.entries()) {
    assert.equal(await card.getByRole("checkbox", {name: "确认目标版本的项目规范变更"}).isChecked(), true);
    assert.equal(await card.getByRole("button", {name: "批准更新基线，保持暂停", exact: true}).isEnabled(), true);
    assert.equal(await card.locator(".engineering-native-rule-changes details").evaluate(
      (node, index) => node === window.retainedRepositoryReviews[index] && node.open, index), true);
  }
  assert.equal(await h.page.evaluate(() => nativeRuleReviews.size), 2);
  assert.equal(submitted.length, 0, "review and polling do not submit either approval");
  h.team.tasks.pop();
  request.scopes.pop();
  await h.tick();
  assert.equal(await h.page.evaluate(() => nativeRuleReviews.size), 1);
  assert.equal(await cards[0].getByRole("checkbox", {name: "确认目标版本的项目规范变更"}).isChecked(), true);
});

for (const previousConsoleOperation of [true, false]) {
  test("committed READY continuation shows exact authorized retry" + (previousConsoleOperation ? " after interrupted operation" : " without a Console operation"), async t => {
    const {h, request, task, step, facts, submitted} = await rescueUi(t);
    const authority = {scope: {team_id: h.team.team_id, project_id: request.project_id, repository_root: task.scope.root},
      task_id: task.task_id, task_intent_sha256: task.task_intent_sha256, task_revision: task.task_revision,
      checkpoint_sequence: task.task_revision, work_item_id: step.work_item_id,
      expected_source_revision: facts.source_revision, execution_baseline_sha256: "8".repeat(64),
      expected_disposition_sha256: step.wait_disposition_sha256, authorization_sha256: "7".repeat(64),
      reference: "原工程授权者明确继续已保存进度的决定"};
    const originalIntent = {action: "RESUME_EXECUTION_BASELINE", project_id: request.project_id, delivery_id: request.id,
      expected_checkpoint_sha256: request.checkpoint_sha256, task_id: task.task_id,
      expected_task_intent_sha256: authority.task_intent_sha256, expected_task_revision: authority.task_revision,
      expected_work_item_id: authority.work_item_id, expected_source_revision: authority.expected_source_revision,
      expected_execution_baseline_sha256: authority.execution_baseline_sha256,
      expected_disposition_sha256: authority.expected_disposition_sha256, reference: authority.reference};
    if (previousConsoleOperation) h.state.operations.push(operation("INTERRUPTED", {
      operation_id: "operation_interrupted_continue", intent: originalIntent, updated_at: "2026-10-06T00:00:00Z",
      error_code: "SERVICE_INTERRUPTED", error_summary: "队列已保存继续决定，启动执行前服务中断。"}));
    step.status = "READY";
    step.wait_disposition = null;
    step.wait_disposition_sha256 = null;
    step.pending_baseline_continuation = authority;
    request.execution = task.execution = {state: "WAITING", responsibility: "engineering", action_required: true,
      reason_code: "BASELINE_CONTINUATION_PENDING", reason: "已授权的执行尚未启动，保留进度保持。", next_action: "继续已授权执行"};
    request.checkpoint_sha256 = "6".repeat(64);
    await h.tick();
    if (await h.page.locator("#notification").isVisible()) await h.close();
    const card = h.page.locator("#detail .engineering-baseline-continuation-pending");
    assert.equal(await card.isVisible(), true);
    assert.match(await card.innerText(), /无需再次批准/);
    assert.equal(await card.getByRole("checkbox").count(), 0);
    assert.equal(await h.page.locator("#detail").getByRole("button", {name: "继续交付", exact: true}).count(), 0);
    assert.equal(submitted.length, 0, "read and polling do not replay delivery automatically");
    await card.getByRole("button", {name: "继续已授权执行", exact: true}).click();
    await h.close();
    assert.equal(submitted.length, 1);
    assert.deepEqual(submitted[0], {...originalIntent, expected_checkpoint_sha256: request.checkpoint_sha256},
      "retry uses saved semantic authority and fresh requirement cursor without another approval");
    assert.equal(await card.getByRole("button", {name: "继续已授权执行", exact: true}).count(), 0,
      "the active retry cannot start a parallel continuation");
  });
}
