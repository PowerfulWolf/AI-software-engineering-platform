const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui, operation } = require("./fixture.cjs");
const { operationManifest } = require("../console-capabilities-fixture.cjs");

function addWait(h) {
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_capabilities"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "原执行结果待核验。", next_action: "平台核验原执行与现场。"};
  const facts = {task_id: "task_capabilities", work_item_id: "work_capabilities", role: "coder",
    task_intent_sha256: "b".repeat(64), source_revision: "c".repeat(40), checkpoint_sequence: 4};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_HUMAN",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  h.team.tasks.push({id: "delivery_capabilities", task_id: facts.task_id, request_id: request.id,
    project_id: request.project_id, title: request.title, status: "IMPLEMENTING", terminal: false,
    scope: request.scopes[0], last_activity: "2026-10-05T00:00:00Z", execution: request.execution,
    assignments: [], documents: [], timeline: [], runs: [], role_queue: [step]});
  return request;
}

test("legacy or unsupported console never receives HANDLE and refreshed capabilities update current controls", async t => {
  const h = await ui(t, {operationManifest: null});
  addWait(h);
  const posts = [];
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const intent = route.request().postDataJSON().intent;
    posts.push(intent);
    return route.fulfill({status: 202, json: operation("QUEUED", {intent,
      operation_id: "operation_capabilities", updated_at: "2026-10-05T01:00:00Z"})});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const panel = h.page.locator('#detail .engineering-wait-panel[data-key="engineering:work_capabilities"]');
  assert.match(await panel.innerText(), /页面与服务版本不匹配/);
  assert.match(await panel.innerText(), /服务空闲时重启 Web Console/);
  assert.equal(await panel.getByRole("button", {name: "让平台处理中断", exact: true}).count(), 0);
  assert.equal(await h.page.evaluate(() => {
    const request = requestById("request_fixture"), step = engineeringWaitSteps(request)[0].step;
    return submitOperation({...engineeringWaitIntent(request, step), action: "HANDLE_DELIVERY_WAIT"});
  }), null);
  assert.equal(posts.length, 0);
  assert.match(await h.page.locator("#notification").innerText(), /本次请求未被受理/);
  await h.close();

  h.state.operationManifest = structuredClone(operationManifest);
  await h.tick();
  const handle = panel.getByRole("button", {name: "让平台处理中断", exact: true});
  assert.equal(await handle.isVisible(), true);
  assert.doesNotMatch(await panel.innerText(), /页面与服务版本不匹配/);
  await handle.evaluate(node => {window.oldCapabilityHandle = node;});
  h.state.operationManifest.supported_actions = ["INSPECT_DELIVERY_WAIT"];
  await h.tick();
  assert.match(await panel.innerText(), /页面与服务版本不匹配/);
  assert.equal(await handle.count(), 0);
  await h.page.evaluate(() => window.oldCapabilityHandle.click());
  assert.equal(posts.length, 0, "a retained button cannot submit after support is withdrawn");
  await h.close();

  h.state.operationManifest = structuredClone(operationManifest);
  await h.tick();
  await handle.click();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].action, "HANDLE_DELIVERY_WAIT");
  assert.equal(posts[0].expected_checkpoint_sequence, 4);
});

test("a stale invalid-input response explains rejection without changing the requirement", async t => {
  const h = await ui(t);
  const request = addWait(h);
  const before = structuredClone(request);
  await h.page.route("http://ui.test/api/v1/operations", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    return route.fulfill({status: 422, json: {error: {code: "INVALID_REQUEST", message: "Operation input is invalid."}}});
  });
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  await h.page.locator("#detail").getByRole("button", {name: "让平台处理中断", exact: true}).click();
  await h.page.locator("#notification").waitFor({state: "visible"});
  const message = await h.page.locator("#notification").innerText();
  assert.match(message, /本次请求未被受理，不是原需求新增的阻塞/);
  assert.match(message, /当前操作和角色执行结束、服务空闲时重启 Web Console/);
  assert.doesNotMatch(message, /Operation input is invalid/);
  assert.deepEqual(request, before);
  assert.equal(h.state.operations.length, 0);
});
