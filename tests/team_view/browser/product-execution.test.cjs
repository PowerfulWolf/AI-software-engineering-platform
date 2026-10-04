const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ui } = require("./fixture.cjs");

test("product execution summary separates phase from engineering wait and retry", async (t) => {
  const h = await ui(t);
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.scopes = [{root: "/fixture", selected_paths: ["."], delivery_id: "delivery_execution"}];
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "WAITING_HUMAN",
    reason: "开发等待工程前提处理。", next_action: "工程团队处理，当前无需产品操作。",
    action_required: false, receipt_uri: "receipt://technical-hash", policy_id: "policy_technical"};
  h.team.tasks.push({id: "delivery_execution", request_id: request.id, project_id: request.project_id,
    title: request.title, status: "IMPLEMENTING", checkpoint_stage: "DELIVERING", terminal: false,
    scope: request.scopes[0], last_activity: "2026-10-04T00:00:00Z", next_action: "old next",
    execution: request.execution, assignments: [], documents: [], timeline: [], runs: [],
    role_queue: [{role: "coder", status: "WAITING_HUMAN", lease_liveness: "UNKNOWN"}]});
  await h.tick();
  await h.requests();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const summary = h.page.locator(".product-execution-summary");
  const text = await summary.innerText();
  assert.match(text, /交付阶段 · 实现/);
  assert.match(text, /当前执行 · 等待工程处理/);
  assert.match(text, /处理方 · 工程团队/);
  assert.doesNotMatch(text, /technical-hash|policy_technical|租约|lease/);
  assert.doesNotMatch(await h.page.locator("#detail").innerText(), /technical-hash|policy_technical/);
  await h.page.getByText("需求工程详情", {exact: true}).click();
  assert.match(await h.page.locator("#detail").innerText(), /technical-hash/);
  request.execution = {...request.execution, state: "RETRY_SCHEDULED", responsibility: "team",
    reason_code: "ROLE_RETRY_SCHEDULED", reason: "已安排开发重试。", available_at: "2026-10-04T00:00:45Z"};
  h.team.tasks[0].execution = request.execution;
  h.team.tasks[0].role_queue[0].status = "RETRY_SCHEDULED";
  await h.tick();
  assert.equal(await h.page.locator(".delivery-flow li.current").count(), 0);
  assert.equal(await h.page.locator(".delivery-flow li.paused").count(), 1);
  assert.match(await summary.innerText(), /等待重试/);
  assert.match(await summary.innerText(), /计划重试时间/);
});
