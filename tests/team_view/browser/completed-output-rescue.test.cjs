const {test} = require("node:test");
const assert = require("node:assert/strict");
const {ui, operation} = require("./fixture.cjs");
const {supportedActions} = require("../console-capabilities-fixture.cjs");

async function waitingCoder(t) {
  const h = await ui(t, {operationManifest: {operation_contract_version: 5, supported_actions: supportedActions}});
  const request = h.team.requests[0];
  request.stage = "DELIVERING";
  request.execution = {state: "WAITING", responsibility: "engineering", reason_code: "EXECUTION_UNCERTAIN",
    reason: "执行结果未接纳，原现场保留。", next_action: "核验原执行及完整开发进度。", action_required: true};
  request.scopes = [{delivery_id: "delivery_coder", root: "/fixture/repository", selected_paths: ["."]}];
  const facts = {task_id: "task_coder", work_item_id: "work_coder", role: "coder", task_intent_sha256: "b".repeat(64),
    source_revision: "c".repeat(40), checkpoint_sequence: 4, classification: "NONTRANSIENT_INFRA"};
  const step = {work_item_id: facts.work_item_id, role: "coder", status: "WAITING_DEPENDENCY",
    wait_disposition_sha256: "d".repeat(64), wait_disposition: {facts, responsibility: "engineering",
      reason: request.execution.reason, next_action: request.execution.next_action}};
  const task = {id: "delivery_coder", task_id: facts.task_id, request_id: request.id, project_id: request.project_id,
    title: "保留同一需求开发进度", task_revision: 4, task_intent_sha256: facts.task_intent_sha256,
    status: "IMPLEMENTING", terminal: false, scope: request.scopes[0], last_activity: "2026-10-11T00:00:00Z",
    execution: request.execution, assignments: [], documents: [], timeline: [], runs: [], role_queue: [step], execution_history: []};
  h.team.tasks.push(task);
  await h.tick();
  return {...h, request, task, step};
}

test("current exact active RESUME states preparation and foreign Task cannot claim it", async t => {
  const h = await waitingCoder(t);
  h.step.status = "WAITING_HUMAN";
  Object.assign(h.step.wait_disposition.facts, {classification: "EXECUTION_BASELINE_PAUSED", execution_baseline_sha256: "8".repeat(64)});
  h.step.wait_disposition.action = "RESUME_EXECUTION_BASELINE";
  h.state.operations.push(operation("RUNNING", {operation_id: "operation_resume", intent: {
    action: "RESUME_EXECUTION_BASELINE", project_id: h.request.project_id, delivery_id: h.request.id,
    expected_checkpoint_sha256: h.request.checkpoint_sha256, task_id: h.task.task_id,
    expected_task_intent_sha256: h.task.task_intent_sha256, expected_task_revision: 4,
    expected_work_item_id: h.step.work_item_id, expected_source_revision: "c".repeat(40),
    expected_execution_baseline_sha256: "8".repeat(64), expected_disposition_sha256: "d".repeat(64), reference: "exact current approval",
  }}));
  await h.tick();
  await h.page.evaluate(() => showDetail("request", "request_fixture"));
  const pause = h.page.locator(".engineering-baseline-pause");
  assert.match(await pause.innerText(), /平台正在准备继续原需求/);
  assert.match(await pause.innerText(), /本轮主执行尚未开始/);
  assert.equal(await pause.getByRole("button", {name: "继续原需求", exact: true}).count(), 0);
  h.state.operations[0].intent.task_id = "task_foreign";
  await h.tick();
  assert.match(await pause.innerText(), /进度已保留 · 交付暂停/);
  assert.doesNotMatch(await pause.innerText(), /平台正在准备继续原需求/);
});

test("Task cannot navigate to an owning requirement from a different Project", async t => {
  const h = await waitingCoder(t);
  h.task.project_id = "project_other";
  await h.tick();
  await h.page.evaluate(() => showDetail("task", "delivery_coder"));
  assert.equal(await h.page.getByRole("button", {name: "打开所属需求", exact: true}).count(), 0);
});
