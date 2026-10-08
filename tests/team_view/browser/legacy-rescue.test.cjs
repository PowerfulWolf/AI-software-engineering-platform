const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");
const { supportedActions } = require("../console-capabilities-fixture.cjs");

async function rescueUi(t, version = 2) {
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
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  assert.match(await card.innerText(), /原执行开始/);
  assert.match(await card.innerText(), /方案核验的整机启动/);
  const checkbox = card.getByRole("checkbox", {name: "确认原执行在同一电脑且已整机重启"});
  const approve = card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true});
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
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await card.getByRole("checkbox").check();
  const approve = card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true});
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
  await card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true}).evaluate(node => {
    window.rejectedRescueApproval = node;
  });
  await card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true}).click();
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
  await card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true}).click();
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

test("local rescue shows auxiliary checks before a distinct exact human stop authorization", async t => {
  const fixture = await rescueUi(t, 3);
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
  const checkbox = card.getByRole("checkbox", {name: "确认原调用及全部派生工具已结束"});
  const approve = card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true});
  assert.equal(await approve.isDisabled(), true);
  await checkbox.check();
  await checkbox.evaluate(node => {window.localRescueCheckbox = node; window.localRescueApproval = node.closest("div").querySelector("button");});
  request.title += " · harmless polling";
  await h.tick();
  assert.equal(await checkbox.evaluate(node => node === window.localRescueCheckbox), true);
  assert.equal(await checkbox.isChecked(), true);
  assert.equal(submitted.length, 1);
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
  const fixture = await rescueUi(t, 3);
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
  assert.equal(await card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true}).count(), 0);
  assert.equal(submitted.length, 1);
  await card.getByRole("button", {name: "重新检查恢复前提", exact: true}).click();
  await h.close();
  assert.equal(submitted.length, 2);
  assert.equal(submitted[1].action, "PROPOSE_EXECUTION_BASELINE");
  assert.equal(Object.hasOwn(submitted[1], "confirm_local_execution_stopped"), false);
});

test("a local stop approval is withdrawn on version downgrade or changed survey", async t => {
  const fixture = await rescueUi(t, 3);
  const {h, request, card, submitted} = fixture;
  await card.getByRole("button", {name: "准备保留进度的恢复方案", exact: true}).click();
  await h.close();
  const plan = localPlanFor(fixture);
  Object.assign(h.state.operations[1], {status: "SUCCEEDED", result: {
    checkpoint_sha256: request.checkpoint_sha256, execution_baseline_plan: plan}});
  await h.tick();
  if (await h.page.locator("#notification").isVisible()) await h.close();
  await card.getByRole("checkbox").check();
  await card.getByRole("button", {name: "批准保留进度并继续原需求", exact: true}).evaluate(node => {window.localStaleApproval = node;});
  h.state.operationManifest.operation_contract_version = 2;
  await h.tick();
  assert.equal(await card.getByRole("checkbox").count(), 0);
  assert.match(await card.innerText(), /当前服务尚不支持此恢复路径/);
  await h.page.evaluate(() => window.localStaleApproval.click());
  assert.equal(submitted.length, 1);
  await h.close();
  h.state.operationManifest.operation_contract_version = 3;
  await h.tick();
  assert.equal(await card.getByRole("checkbox").isChecked(), false);
  await card.getByRole("checkbox").check();
  plan.plan_sha256 = "8".repeat(64);
  plan.facts.legacy_containment.local_execution_survey.survey_sha256 = "9".repeat(64);
  await h.tick();
  assert.equal(await card.getByRole("checkbox").isChecked(), false);
  await h.page.evaluate(() => window.localStaleApproval.click());
  assert.equal(submitted.length, 1);
});
