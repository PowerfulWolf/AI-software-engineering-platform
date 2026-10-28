const assert = require("node:assert/strict");
const {test} = require("node:test");
const {ui, operation} = require("./fixture.cjs");

async function localStopUi(t) {
  const h = await ui(t, {operationManifest: {operation_contract_version: 12,
    supported_actions: require("../console-capabilities-fixture.cjs").supportedActions}});
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_local_stop"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "原 Coder 执行结果未知。", next_action: "平台核验原执行和完整草稿。"};
  const facts = {task_id: "task_local_stop", work_item_id: "work_local_stop", role: "coder",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 11};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  h.team.tasks.push({id: "delivery_local_stop", task_id: facts.task_id, request_id: request.id,
    project_id: request.project_id, title: request.title, status: "IMPLEMENTING", terminal: false,
    scope: request.scopes[0], last_activity: "2026-10-27T12:00:00Z", execution: request.execution,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: [step]});
  const bound = {action: "INSPECT_DELIVERY_WAIT", project_id: request.project_id, delivery_id: request.id,
    expected_checkpoint_sha256: request.checkpoint_sha256, work_item_id: step.work_item_id,
    expected_disposition_sha256: step.wait_disposition_sha256, expected_task_intent_sha256: facts.task_intent_sha256,
    expected_source_revision: facts.source_revision, expected_checkpoint_sequence: facts.checkpoint_sequence};
  const proof = {kind: "delivery_wait_investigation", ...facts,
    disposition_sha256: step.wait_disposition_sha256, proof_sha256: "e".repeat(64),
    original_run_id: "run_64dcd04b0e54432eae481068d7e80285", inspected_at: "2026-10-27T12:10:00Z",
    missing: ["OUTCOME_UNKNOWN", "STOP_UNRECORDED", "CHECKPOINT_UNAVAILABLE", "BUDGET_EXHAUSTED"],
    permitted_resolutions: [], local_stop_confirmation_available: false,
    next_action: "原执行结果和停止记录仍未知，冻结额度已用尽。"};
  h.state.operations.push(operation("SUCCEEDED", {operation_id: "operation_local_stop_inspect", intent: bound,
    result: {checkpoint_sha256: request.checkpoint_sha256, engineering_wait_investigation: proof}}));
  const submitted = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    submitted.push(intent);
    const record = operation("QUEUED", {operation_id: "operation_local_stop_" + submitted.length, intent});
    h.state.operations.push(record);
    return route.fulfill({status: 202, json: record});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  if (await h.page.locator("#notification").isVisible()) await h.close();
  return {h, request, step, proof, submitted,
    panel: h.page.locator('#detail section.engineering-wait-panel[data-key="engineering:work_local_stop"]')};
}

test("local stop declaration is withheld without exact server capability and never submitted by polling", async t => {
  const {h, proof, step, submitted, panel} = await localStopUi(t);
  assert.equal(await panel.locator(".engineering-local-stop-panel").count(), 0);
  await h.tick();
  assert.equal(submitted.length, 0);
  proof.local_stop_confirmation_available = true;
  proof.missing = ["OUTCOME_UNKNOWN", "STOP_UNRECORDED", "CHECKPOINT_UNAVAILABLE"];
  await h.tick();
  assert.equal(await panel.locator(".engineering-local-stop-panel").count(), 0,
    "capability alone cannot bypass the exact exhausted Coder wait shape");
  proof.missing.push("BUDGET_EXHAUSTED");
  step.role = "qa";
  step.wait_disposition.facts.role = "qa";
  await h.tick();
  assert.equal(await panel.locator(".engineering-local-stop-panel").count(), 0,
    "another role cannot use a Coder-only confirmation");
  assert.equal(submitted.length, 0);
});

test("authorized local stop confirmation binds current proof, requires declaration and saved reference", async t => {
  const {h, request, proof, submitted, panel} = await localStopUi(t);
  proof.local_stop_confirmation_available = true;
  await h.tick();
  const box = panel.locator(".engineering-local-stop-panel");
  const declaration = box.getByRole("checkbox", {name: "确认原 Coder 调用及全部派生工具已结束"});
  const reference = box.getByRole("textbox", {name: "已封存的授权记录 ID"});
  const submit = box.getByRole("button", {name: "记录本机停止确认并处理旧任务", exact: true});
  assert.equal(await box.isVisible(), true);
  assert.match(await box.innerText(), /同一账户本地执行/);
  assert.match(await box.innerText(), /今后不能再写入原 Coder 工作区/);
  assert.match(await box.innerText(), /旧结果继续保持未知|原结果仍未知/);
  assert.equal(await declaration.isChecked(), false);
  assert.equal(await reference.inputValue(), "");
  assert.equal(await submit.isDisabled(), true);
  await declaration.check();
  assert.equal(await submit.isDisabled(), true);
  await reference.fill("call_a7e4ebe2aed34bad899f8cc3588da3b5");
  assert.equal(await submit.isEnabled(), true);
  await reference.evaluate(node => {window.savedLocalStopReference = node;});
  request.title += " · 轮询标题变化";
  await h.tick();
  assert.equal(await reference.evaluate(node => node === window.savedLocalStopReference), true);
  assert.equal(await reference.inputValue(), "call_a7e4ebe2aed34bad899f8cc3588da3b5");
  assert.equal(submitted.length, 0, "typing, checking and polling cannot issue the declaration");
  await submit.click();
  assert.equal(submitted.length, 1);
  assert.equal(submitted[0].action, "HANDLE_DELIVERY_WAIT");
  assert.equal(submitted[0].confirm_local_execution_stopped, true);
  assert.equal(submitted[0].local_stop_reference, "call_a7e4ebe2aed34bad899f8cc3588da3b5");
  assert.equal(submitted[0].expected_checkpoint_sha256, request.checkpoint_sha256);
  assert.equal(submitted[0].expected_disposition_sha256, "d".repeat(64));
  assert.equal(Object.hasOwn(submitted[0], "local_stop_confirmed_at"), false);
});

test("a retained local stop button cannot submit after proof capability or checkpoint changes", async t => {
  const {h, request, proof, submitted, panel} = await localStopUi(t);
  proof.local_stop_confirmation_available = true;
  await h.tick();
  const box = panel.locator(".engineering-local-stop-panel");
  await box.getByRole("checkbox").check();
  await box.getByRole("textbox", {name: "已封存的授权记录 ID"}).fill("resolution_saved_123");
  const submit = box.getByRole("button", {name: "记录本机停止确认并处理旧任务", exact: true});
  await submit.evaluate(node => {window.oldLocalStopSubmit = node;});
  proof.local_stop_confirmation_available = false;
  await h.tick();
  assert.equal(await panel.locator(".engineering-local-stop-panel").count(), 0);
  await h.page.evaluate(() => window.oldLocalStopSubmit.click());
  assert.equal(submitted.length, 0);
  proof.local_stop_confirmation_available = true;
  await h.tick();
  const newBox = panel.locator(".engineering-local-stop-panel");
  await newBox.getByRole("checkbox").check();
  await newBox.getByRole("textbox", {name: "已封存的授权记录 ID"}).fill("resolution_saved_123");
  await newBox.getByRole("button", {name: "记录本机停止确认并处理旧任务", exact: true})
    .evaluate(node => {window.checkpointLocalStopSubmit = node;});
  request.checkpoint_sha256 = "f".repeat(64);
  await h.tick();
  await h.page.evaluate(() => window.checkpointLocalStopSubmit.click());
  assert.equal(submitted.length, 0);
});
